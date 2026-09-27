/** Optional Cloudflare entrypoint in front of the Vercel backend. No API keys here. */
export default {
  async fetch(request, env) {
    let upstream;
    try { upstream = new URL(env.UPSTREAM_ORIGIN); } catch { return new Response('Configure UPSTREAM_ORIGIN first', {status:503}); }
    if(upstream.protocol!=='https:'||!upstream.hostname.endsWith('.vercel.app')||upstream.username||upstream.password||upstream.port||upstream.pathname!=='/'||upstream.search||upstream.hash){
      return new Response('UPSTREAM_ORIGIN must be the exact HTTPS Vercel origin', {status:503});
    }
    const incoming = new URL(request.url);
    const upgrade = request.headers.get('Upgrade')?.toLowerCase()==='websocket';
    if ((upgrade||!['GET','HEAD'].includes(request.method)) && request.headers.get('Origin')!==incoming.origin) {
      return new Response('Cross-origin request denied', {status:403});
    }
    const target = new URL(upstream.origin);
    target.pathname=incoming.pathname;target.search=incoming.search;
    const headers=new Headers(request.headers);
    for(const h of ['host','x-forwarded-host','x-forwarded-proto','x-forwarded-for']) headers.delete(h);
    const init={method:request.method,headers,redirect:'manual',duplex:'half'};
    if(!['GET','HEAD'].includes(request.method))init.body=request.body;
    try {
      const response=await fetch(new Request(target,init),{cf:{cacheTtl:0,cacheEverything:false}});
      // Preserve the attached WebSocket object: never reconstruct a 101 response.
      if(response.status===101)return response;
      const result=new Response(response.body,response);
      result.headers.set('Cache-Control','no-store');
      result.headers.set('X-Content-Type-Options','nosniff');
      result.headers.set('Referrer-Policy','no-referrer');
      result.headers.set('X-Robots-Tag','noindex');
      return result;
    } catch {
      return new Response('Upstream unavailable. No replacement transcription was generated.',{status:502,headers:{'Cache-Control':'no-store'}});
    }
  }
};
