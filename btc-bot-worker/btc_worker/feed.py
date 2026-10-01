import json, math, time
from datetime import datetime, timezone

def millis(raw):
    try:
        number=float(raw)
        return int(number*1000 if number<1e12 else number)
    except (TypeError,ValueError):
        return int(datetime.fromisoformat(str(raw).replace('Z','+00:00')).timestamp()*1000)

def values(raw):
    if isinstance(raw,dict):
        if 'value' in raw and ('time' in raw or 'timestamp' in raw) and raw.get('id','BRTI')=='BRTI':
            try:
                p=float(raw['value']);t=millis(raw.get('time',raw.get('timestamp')))
                if math.isfinite(p) and p>0: yield t,p
            except (TypeError,ValueError,OverflowError): pass
        else:
            for v in raw.values(): yield from values(v)
    elif isinstance(raw,list):
        for v in raw: yield from values(v)

class Reference:
    def __init__(self): self.points={};self.latest=None;self.final_average=None
    def add(self,t,p,now=None):
        now=now or int(time.time()*1000)
        if t>now+1000 or t<now-3600000 or not math.isfinite(p) or p<=0:return
        second=t//1000
        previous=self.points.get(second)
        if previous is None or t>previous[0]: self.points[second]=(t,p)
        if self.latest is None or t>self.latest['time']:self.latest={'price':p,'time':t}
        self.points={s:v for s,v in self.points.items() if s>now//1000-3600}
    def consume(self,message):
        if message.get('type')!='cfbenchmarks_value':return
        msg=message.get('msg',{})
        if msg.get('index_id')!='BRTI':return
        raw=msg.get('data',{})
        if isinstance(raw,str):raw=json.loads(raw)
        for t,p in values(raw):self.add(t,p)
        avg=msg.get('last_60s_windowed_average_15min')
        if avg:
            try:
                count=int(avg['window_size']);p=float(avg['value'])
                if 0<count<=60 and math.isfinite(p) and p>0:self.final_average={'price':p,'count':count,'startAt':int(avg['window_start_ts_ms']),'endAt':int(avg['window_end_ts_exclusive'])}
            except (KeyError,TypeError,ValueError):pass
    def candles(self,now=None):
        now=now or int(time.time()*1000);buckets={}
        for second,point in self.points.items():buckets.setdefault(second//60*60,[]).append(point)
        output=[]
        for minute,points in sorted(buckets.items()):
            if minute*1000>=now//60000*60000 or len(points)<45:continue
            points.sort();prices=[p for _,p in points]
            output.append({'time':minute,'open':prices[0],'close':prices[-1],'high':max(prices),'low':min(prices),'volume':0})
        return output[-31:]

def normalize_market(raw,now):
    try:
        ticker=raw['ticker'];open_at=millis(raw['open_time']);close_at=millis(raw['close_time']);target=raw.get('floor_strike')
        if target is None:
            label=raw.get('yes_sub_title','').split(':',1)[-1].replace('$','').replace(',','').strip()
            try:target=float(label)
            except ValueError:target=None
        if not ticker.startswith('KXBTC15M-') or not(open_at<=now<close_at) or raw.get('status') not in ('active','open'):return None
        return {'ticker':ticker,'openAt':open_at,'closeAt':close_at,'target':float(target) if target else None,'status':raw['status']}
    except (KeyError,TypeError,ValueError):return None

def normalize_book(raw,at):
    book=raw.get('orderbook_fp')
    if not isinstance(book,dict):raise ValueError('Fixed-point order book missing')
    out={'at':at}
    for side in ('yes','no'):
        levels=[]
        for p,q in book.get(side+'_dollars',[]):
            p,q=float(p),float(q)
            if math.isfinite(p) and math.isfinite(q) and 0<=p<=1 and q>=0:levels.append([p,q])
        out[side]=sorted(levels,reverse=True)[:100]
    return out
