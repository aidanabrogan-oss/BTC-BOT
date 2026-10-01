"""One-contract IOC demo smoke test. The production host is never used."""
import argparse,asyncio,json,os,sqlite3,time,uuid
from .api import Kalshi,DEMO

def payload(ticker,outcome,price,client_id):
    if not ticker.startswith('KXBTC15M-') or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in ticker):raise ValueError('Use a BTC 15-minute demo ticker')
    if outcome not in ('yes','no') or not .01<=price<=.95:raise ValueError('Invalid outcome or limit price')
    # V2 always uses a YES-book price. Paying 40c for NO means an ASK at 60c.
    yes_price=price if outcome=='yes' else 1-price
    return {'ticker':ticker,'client_order_id':client_id,'side':'bid' if outcome=='yes' else 'ask','count':'1.00','price':f'{yes_price:.4f}','time_in_force':'immediate_or_cancel','cancel_order_on_pause':True,'self_trade_prevention_type':'taker_at_cross'}

async def main(args):
    client_id=str(uuid.uuid4());body=payload(args.ticker,args.outcome,args.limit,client_id)
    if not args.submit:
        print(json.dumps({'mode':'DEMO DRY RUN','host':DEMO,'request':body,'submitted':False},indent=2));return
    if not args.journal:raise SystemExit('--journal is required for durable submission/reconciliation records')
    api=Kalshi(os.environ['KALSHI_DEMO_API_KEY_ID'],os.environ['KALSHI_DEMO_PRIVATE_KEY'],'demo')
    db=sqlite3.connect(args.journal);db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY,ticker TEXT,state TEXT,request TEXT,response TEXT,created REAL)')
    if db.execute("SELECT 1 FROM attempts WHERE state IN ('submitting','uncertain')").fetchone():raise SystemExit('An earlier demo submission is unresolved. Reconcile its client_order_id before submitting again.')
    # No POST is retried. Persist intent before the single side effect.
    db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)',(client_id,args.ticker,'submitting',json.dumps(body),None,time.time()));db.commit()
    try:
        response=await api.request('/trade-api/v2/portfolio/events/orders','POST',body)
        db.execute('UPDATE attempts SET state=?,response=? WHERE id=?',('acknowledged',json.dumps(response),client_id));db.commit()
        print(json.dumps({'mode':'demo','client_order_id':client_id,'acknowledged':True,'response':response},indent=2))
        order_id=response.get('order_id')
        if not order_id:raise RuntimeError('Missing order ID')
        if order_id:
            confirmed=await api.request('/trade-api/v2/portfolio/orders/'+order_id)
            db.execute('UPDATE attempts SET state=?,response=? WHERE id=?',('reconciled',json.dumps(confirmed),client_id));db.commit()
            print(json.dumps({'confirmed_order':confirmed},indent=2))
    except Exception:
        db.execute('UPDATE attempts SET state=? WHERE id=?',('uncertain',client_id));db.commit()
        raise SystemExit('Demo outcome uncertain; do not resubmit. Reconcile the saved client_order_id with Kalshi demo orders.')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ticker',required=True);p.add_argument('--outcome',choices=['yes','no'],default='yes');p.add_argument('--limit',type=float,default=.1);p.add_argument('--submit',action='store_true');p.add_argument('--journal');asyncio.run(main(p.parse_args()))
