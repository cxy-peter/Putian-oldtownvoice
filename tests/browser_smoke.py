"""Optional UI integration test. Uses synthetic microphone and local mock ASR, never cloud.
Install playwright separately. CHROMIUM_PATH can point to a system browser.
"""
import asyncio, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from app import create_app

async def main():
    out=Path(os.environ.get('TEST_ARTIFACTS','test-artifacts'));out.mkdir(parents=True,exist_ok=True)
    checks=[];requests=[]
    async def mock_ws(request):
        ws=web.WebSocketResponse();await ws.prepare(request);start=await ws.receive_json();requests.append(start)
        q3=start.get('type')=='session.update';await ws.send_json({'type':'session.updated'} if q3 else {'header':{'event':'task-started'}})
        frames=0
        async for msg in ws:
            if msg.type==web.WSMsgType.BINARY or (msg.type==web.WSMsgType.TEXT and json.loads(msg.data).get('type')=='input_audio_buffer.append'):
                frames+=1
                if frames==1:await ws.send_json({'type':'conversation.item.input_audio_transcription.text','item_id':'1','text':'模拟上游','stash':'测试'} if q3 else {'header':{'event':'result-generated'},'payload':{'output':{'sentence':{'sentence_id':1,'text':'模拟上游测试','sentence_end':False}}}})
            elif msg.type==web.WSMsgType.TEXT:
                requests.append(json.loads(msg.data))
                await ws.send_json({'type':'conversation.item.input_audio_transcription.completed','item_id':'1','transcript':'模拟上游：句尾已保留（非莆仙话实测）。'} if q3 else {'header':{'event':'result-generated'},'payload':{'output':{'sentence':{'sentence_id':1,'text':'模拟上游：句尾已保留（非莆仙话实测）。','sentence_end':True}}}})
                await ws.send_json({'type':'session.finished'} if q3 else {'header':{'event':'task-finished'}});break
        await ws.close();return ws
    async def mock_translate(request):
        requests.append(await request.json());return web.json_response({'choices':[{'message':{'content':'测试译文（模拟接口，不代表识别效果）。'}}]})
    upstream=web.Application();upstream.router.add_get('/mock',mock_ws);upstream.router.add_post('/translate',mock_translate)
    ur=web.AppRunner(upstream);await ur.setup();await web.TCPSite(ur,'127.0.0.1',18901).start()
    with tempfile.TemporaryDirectory() as data:
        app=create_app({'PORT':'18902','DATA_DIR':data,'APP_ACCESS_CODE':'local-test-access-code','DASHSCOPE_API_KEY':'local-test-placeholder'})
        app['endpoints']=('ws://127.0.0.1:18901/mock','ws://127.0.0.1:18901/mock','http://127.0.0.1:18901/translate')
        ar=web.AppRunner(app);await ar.setup();await web.TCPSite(ar,'127.0.0.1',18902).start()
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or '/usr/bin/chromium',headless=True,args=['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
                ctx=await browser.new_context(viewport={'width':1440,'height':1040},permissions=['microphone']);page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto('http://127.0.0.1:18902');await page.wait_for_selector('#account');checks.append('desktop page loaded')
                assert await page.locator('#engine').input_value()=='qwen31';checks.append('default model selected')
                await page.locator('#account').click();await page.locator('#accessCode').fill('local-test-access-code');await page.locator('#login').click();await page.wait_for_function("document.getElementById('settings').open===false");checks.append('login')
                await page.locator('[data-tab="corpus"]').click();await page.locator('#termText').fill('测试词条');await page.locator('#termMeaning').fill('仅用于软件测试');await page.locator('#addTerm').click();await page.locator('#saveCorpus').click();await page.wait_for_function("document.getElementById('revision').textContent.includes('版本 2')");checks.append('save corpus revision')
                await page.reload();await page.locator('[data-tab="corpus"]').click();await page.get_by_text('测试词条 · 3',exact=False).wait_for();checks.append('corpus persists across reload')
                await page.locator('#exampleSource').fill('测试原文');await page.locator('#exampleTarget').fill('测试含义');await page.locator('#exampleReviewed').check();await page.locator('#addExample').click();await page.locator('#saveCorpus').click();await page.wait_for_function("document.getElementById('revision').textContent.includes('版本 3')");checks.append('save reviewed example')
                await page.locator('[data-tab="live"]').click();await page.locator('#consent').check();await page.locator('#engine').select_option('collect');await page.locator('#record').click();await page.wait_for_function("document.getElementById('record').textContent.includes('结束')");await page.wait_for_timeout(1300);await page.locator('#record').click();await page.locator('#playback').wait_for();checks.append('AudioWorklet recording and WAV playback')
                assert not any('payload' in r for r in requests);checks.append('collection mode makes no ASR request')
                await page.locator('[data-tab="samples"]').click();await page.locator('#speaker').fill('synthetic-test');await page.locator('#reference').fill('合成测试音频的测试标注，不是实际语料');await page.locator('#sampleReviewed').check();await page.locator('#saveSample').click();await page.get_by_text('synthetic-test ·',exact=False).wait_for();checks.append('private audio and reviewed labels saved')
                async with page.expect_download() as d:await page.locator('#exportDataset').click()
                download=await d.value;assert download.suggested_filename.endswith('.zip');checks.append('private dataset export')
                await page.locator('[data-tab="live"]').click();await page.locator('#engine').select_option('qwen31');await page.locator('#record').click();await page.get_by_text('模拟上游测试',exact=True).wait_for();checks.append('live draft arrives while microphone recording')
                await page.locator('#record').click();await page.get_by_text('模拟上游：句尾已保留（非莆仙话实测）。',exact=True).wait_for();await page.wait_for_function("document.getElementById('resultStatus').textContent==='转写结束'");checks.append('final tail received before WebSocket closes')
                assert await page.locator('.segment').count()==1;checks.append('draft replaced not duplicated')
                await page.get_by_role('button',name='翻译 / 重试').click();await page.get_by_text('测试译文（模拟接口，不代表识别效果）。',exact=True).wait_for();checks.append('translation without overwriting raw transcript')
                await page.get_by_role('button',name='人工校正',exact=True).click();await page.get_by_label('人工校正文本').fill('人工修改测试');assert '模拟上游' in await page.locator('.raw').inner_text();checks.append('manual correction preserves ASR source')
                await page.get_by_role('button',name='人工校正',exact=True).click()
                await page.screenshot(path=str(out/'desktop.png'),full_page=True);checks.append('desktop screenshot')
                await page.locator('#engine').select_option('qwen3');await page.locator('#record').click();await page.get_by_text('模拟上游测试',exact=True).wait_for();await page.locator('#record').click();await page.wait_for_function("document.getElementById('resultStatus').textContent==='转写结束'");assert await page.locator('.segment').count()==1;checks.append('Qwen3 alternative WebSocket protocol')
                await page.set_viewport_size({'width':390,'height':844});await page.screenshot(path=str(out/'mobile.png'),full_page=True);assert await page.evaluate('document.documentElement.scrollWidth<=window.innerWidth');checks.append('390px layout without horizontal overflow')
                await page.locator('[data-tab="corpus"]').click();assert await page.locator('#termList').is_visible();await page.locator('[data-tab="samples"]').click();assert await page.locator('#reference').is_visible();checks.append('mobile tabs navigate')
                assert not errors,errors;checks.append('no uncaught JavaScript errors')
                await ctx.close();await browser.close()
        finally:await ar.cleanup();await ur.cleanup()
    (out/'browser-report.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'source':'local mocked upstream and synthetic microphone; not live ASR, not real phone hardware'},ensure_ascii=False,indent=2))
    print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
