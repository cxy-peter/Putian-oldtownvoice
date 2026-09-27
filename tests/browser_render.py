"""Offline DOM/UI test, using in-memory API fixtures. No browser network or microphone.
Separate tests/test_app.py covers actual local HTTP and WebSocket transport.
"""
import asyncio,json,os,re,sys
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
async def main():
    out=Path(os.environ.get('TEST_ARTIFACTS','test-artifacts'));out.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),args=['--no-sandbox']);page=await browser.new_page(viewport={'width':1440,'height':1080});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));checks=[]
        html=(ROOT/'public/index.html').read_text();html=re.sub(r'<script.*?</script>','',html,flags=re.S);html=re.sub(r'<link[^>]*>','',html)
        await page.set_content(html);await page.add_style_tag(content=(ROOT/'public/styles.css').read_text())
        await page.add_script_tag(content='''window.fixture={authenticated:false,corpus:{revision:1,terms:[],examples:[]},samples:[]}; window.fetch=async(url,opt={})=>{let f=window.fixture,d=opt.body?JSON.parse(opt.body):{}; if(url==='/api/status')return {ok:true,json:async()=>({authenticated:f.authenticated,keyConfigured:true})}; if(url==='/api/login'){f.authenticated=true;return {ok:true,json:async()=>({ok:true})};} if(url==='/api/corpus'){if(opt.method==='PUT')f.corpus={...d,revision:f.corpus.revision+1};return {ok:true,json:async()=>JSON.parse(JSON.stringify(f.corpus))};} if(url==='/api/samples'){if(opt.method==='POST')f.samples.push({...d,id:'test',seconds:1});return {ok:true,json:async()=>JSON.parse(JSON.stringify(f.samples))};} if(url==='/api/translate')return {ok:true,json:async()=>({text:'模拟译文，仅用于界面测试。'})};return {ok:false,json:async()=>({error:'测试未配置的路由'})};};''')
        await page.add_script_tag(content=(ROOT/'public/app.js').read_text());await page.wait_for_timeout(100);checks.append('page and script rendered in memory')
        assert await page.locator('#engine').input_value()=='qwen31';checks.append('default model correct')
        await page.locator('#account').click();await page.locator('#accessCode').fill('test-access-code');await page.locator('#login').click();await page.wait_for_function("document.getElementById('settings').open===false");checks.append('login modal and state')
        await page.locator('[data-tab="corpus"]').click();await page.locator('#termText').fill('测试词条');await page.locator('#termMeaning').fill('人工含义测试');await page.locator('#addTerm').click();await page.locator('#saveCorpus').click();assert '版本 2' in await page.locator('#revision').inner_text();checks.append('add term and save revision')
        await page.locator('#exampleSource').fill('测试原文');await page.locator('#exampleTarget').fill('测试对应');await page.locator('#exampleReviewed').check();await page.locator('#addExample').click();await page.locator('#saveCorpus').click();assert '版本 3' in await page.locator('#revision').inner_text();checks.append('reviewed example')
        await page.locator('#termText').fill('<img src=x onerror=alert(1)>');await page.locator('#addTerm').click();assert await page.locator('#termList img').count()==0;checks.append('user terms rendered as text not HTML')
        await page.screenshot(path=str(out/'corpus.png'),full_page=True)
        await page.locator('[data-tab="live"]').click();await page.evaluate("receiveSegment({id:'1',text:'模拟上游草稿',final:false})");assert await page.locator('.segment').count()==1;checks.append('draft rendering')
        await page.evaluate("receiveSegment({id:'1',text:'模拟上游：句尾已保留（非莆仙话实测）。',final:true})");assert await page.locator('.segment').count()==1;checks.append('final replaces draft')
        await page.get_by_role('button',name='翻译 / 重试').click();await page.get_by_text('模拟译文，仅用于界面测试。',exact=True).wait_for();checks.append('separate translation display')
        await page.get_by_role('button',name='人工校正',exact=True).click();await page.get_by_label('人工校正文本').fill('人工校正测试');assert '模拟上游' in await page.locator('.raw').inner_text();checks.append('correction leaves raw intact');await page.get_by_role('button',name='人工校正',exact=True).click()
        await page.evaluate("document.getElementById('resultStatus').textContent='界面测试 · 模拟数据'");await page.screenshot(path=str(out/'desktop.png'),full_page=True);checks.append('desktop screenshot')
        await page.evaluate("chunks=[new Uint8Array(32000)];elapsed=1;retainAudio();");assert await page.locator('#playback').is_visible();assert await page.evaluate('audioBlob.size')==32044;checks.append('WAV encoding and playback element')
        await page.locator('[data-tab="samples"]').click();await page.locator('#speaker').fill('synthetic-test');await page.locator('#reference').fill('测试标注');await page.locator('#sampleReviewed').check();await page.locator('#saveSample').click();await page.get_by_text('synthetic-test ·',exact=False).wait_for();checks.append('annotation save UI')
        await page.set_viewport_size({'width':390,'height':844});await page.locator('[data-tab="live"]').click();await page.screenshot(path=str(out/'mobile.png'),full_page=True);assert await page.evaluate('document.documentElement.scrollWidth<=window.innerWidth');checks.append('390px mobile no horizontal overflow')
        await page.locator('[data-tab="corpus"]').click();assert await page.locator('#termList').is_visible();await page.locator('[data-tab="samples"]').click();assert await page.locator('#reference').is_visible();checks.append('mobile tabs')
        assert not errors,errors;checks.append('no uncaught JavaScript errors')
        await browser.close()
    report={'passed':len(checks),'checks':checks,'scope':'Offline DOM/UI fixtures; no live browser HTTP, microphone, cloud ASR or real handset test.'};(out/'browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
