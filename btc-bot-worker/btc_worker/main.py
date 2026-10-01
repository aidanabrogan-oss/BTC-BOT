import asyncio,json,logging,os,signal,time,uuid
from datetime import datetime,timezone
from urllib.parse import urlencode,urlparse
from websockets.asyncio.client import connect
from .api import Kalshi,http_json
from .feed import Reference,values,normalize_market,normalize_book

log=logging.getLogger('btc-bot');NOW=lambda:int(time.time()*1000)
class Worker:
    def __init__(self,api,site,service_token,worker_secret):
        if urlparse(site).scheme!='https' or urlparse(site).netloc!='btc-bot.aidan-brogan15.chatgpt.site':raise ValueError('Use the published BTC BOT HTTPS origin')
        self.api=api;self.site=site.rstrip('/');self.headers={'OAI-Sites-Authorization':'Bearer '+service_token,'X-BTC-Worker-Secret':worker_secret}
        self.reference=Reference();self.market=None;self.market_at=0;self.book=None;self.connection='Connecting BRTI';self.runner_id=str(uuid.uuid4());self.sequence=0;self.stop=asyncio.Event()
    async def warmup(self):
        try:
            stamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
            result=await self.api.request('/trade-api/v2/cfbenchmarks/history/values?'+urlencode({'id':'BRTI','timespan':'HOUR','timestamp':stamp}))
            for t,p in values(result.get('data',{})):self.reference.add(t,p)
        except Exception:log.info('BRTI history unavailable; collecting live minute history')
    async def stream(self):
        delay=1
        while not self.stop.is_set():
            try:
                path='/trade-api/ws/v2'
                async with connect('wss://external-api-ws.kalshi.com'+path,additional_headers=self.api.headers('GET',path),ping_interval=20,ping_timeout=10,open_timeout=10,max_size=2**22) as ws:
                    await ws.send(json.dumps({'id':1,'cmd':'subscribe','params':{'channels':['cfbenchmarks_value'],'index_ids':['BRTI']}}))
                    delay=1;self.connection='BRTI stream connected'
                    async for frame in ws:
                        msg=json.loads(frame)
                        if msg.get('type')=='error':raise RuntimeError('BRTI subscription rejected')
                        self.reference.consume(msg)
                        if self.stop.is_set():break
            except asyncio.CancelledError:raise
            except Exception:
                self.connection='BRTI disconnected; reconnecting';log.warning('BRTI disconnected; new entries require fresh data')
                await asyncio.sleep(delay);delay=min(delay*2,30)
    async def discover(self):
        while not self.stop.is_set():
            try:
                now=NOW();params={'series_ticker':'KXBTC15M','limit':100,'min_close_ts':now//1000,'max_close_ts':now//1000+1800}
                d=await self.api.request('/trade-api/v2/markets?'+urlencode(params));candidates=[normalize_market(m,NOW()) for m in d.get('markets',[])];candidates=[m for m in candidates if m]
                selected=min(candidates,key=lambda m:m['closeAt']) if candidates else None
                if not selected or selected['ticker']!=(self.market or {}).get('ticker'):self.book=None
                self.market=selected;self.market_at=NOW()
            except Exception:log.warning('Kalshi market discovery failed; freshness checks remain active')
            await asyncio.sleep(5)
    async def quotes(self):
        while not self.stop.is_set():
            m=self.market
            if m:
                try:
                    d=await self.api.request('/trade-api/v2/markets/'+m['ticker']+'/orderbook?depth=10')
                    if self.market and self.market['ticker']==m['ticker']:self.book=normalize_book(d,NOW())
                except Exception:pass
            await asyncio.sleep(1)
    async def deliver(self):
        delay=1
        while not self.stop.is_set():
            self.sequence+=1
            payload={'runnerId':self.runner_id,'sequence':self.sequence,'sentAt':NOW(),'reference':self.reference.latest,'candles':self.reference.candles(),'market':self.market,'marketAt':self.market_at,'book':self.book,'finalAverage':self.reference.final_average,'connection':self.connection}
            try:
                r=await asyncio.to_thread(http_json,self.site+'/api/engine/worker','POST',self.headers,payload,25)
                delay=1
                if not r.get('accepted'):log.warning('Worker lease busy; waiting')
            except Exception:
                log.warning('Cloud journal delivery unavailable; no local paper or real orders are placed')
                delay=min(delay*2,30)
            await asyncio.sleep(delay)
    async def run(self):
        await self.warmup()
        tasks=[asyncio.create_task(fn()) for fn in [self.stream,self.discover,self.quotes,self.deliver]]
        await self.stop.wait()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

async def main():
    required=['KALSHI_API_KEY_ID','KALSHI_PRIVATE_KEY','BTC_BOT_SITE_TOKEN','BTC_BOT_WORKER_SECRET']
    missing=[name for name in required if not os.environ.get(name)]
    if missing:raise SystemExit('Missing required secret settings: '+', '.join(missing))
    api=Kalshi(os.environ['KALSHI_API_KEY_ID'],os.environ['KALSHI_PRIVATE_KEY'])
    worker=Worker(api,os.environ.get('BTC_BOT_SITE_URL','https://btc-bot.aidan-brogan15.chatgpt.site'),os.environ['BTC_BOT_SITE_TOKEN'],os.environ['BTC_BOT_WORKER_SECRET'])
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,worker.stop.set)
    await worker.run()
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(main())
