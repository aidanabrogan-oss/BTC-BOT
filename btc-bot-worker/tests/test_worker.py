import asyncio,base64,unittest,tempfile,sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding,ed25519
from btc_worker.api import Kalshi,DEMO
from btc_worker.demo import payload
from btc_worker.feed import Reference,normalize_book,normalize_market
class WorkerTests(unittest.TestCase):
    def key(self,ed=False):
        key=ed25519.Ed25519PrivateKey.generate() if ed else rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        return key,pem
    def test_signatures_exclude_query(self):
        for ed in (False,True):
            key,pem=self.key(ed);api=Kalshi('test',pem);headers=api.headers('GET','/trade-api/v2/markets?limit=1');message=(headers['KALSHI-ACCESS-TIMESTAMP']+'GET/trade-api/v2/markets').encode();sig=base64.b64decode(headers['KALSHI-ACCESS-SIGNATURE'])
            if ed:key.public_key().verify(sig,message)
            else:key.public_key().verify(sig,message,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
    def test_production_writes_rejected(self):
        _,pem=self.key();api=Kalshi('test',pem)
        with self.assertRaises(PermissionError):asyncio.run(api.request('/trade-api/v2/portfolio/events/orders','POST',{}))
    def test_demo_prices_are_yes_book_prices(self):
        yes=payload('KXBTC15M-TEST','yes',.4,'id');no=payload('KXBTC15M-TEST','no',.4,'id');self.assertEqual(yes['price'],'0.4000');self.assertEqual(no['price'],'0.6000');self.assertEqual(no['side'],'ask');self.assertEqual(no['time_in_force'],'immediate_or_cancel');self.assertEqual(no['count'],'1.00')
    def test_bar_coverage_and_duplicate_samples(self):
        now=1800000120000;ref=Reference();minute=(now//60000-1)*60000
        for i in range(60):ref.add(minute+i*1000,100+i,now)
        for i in range(60):ref.add(minute+i*1000,9000,now)
        bars=ref.candles(now);self.assertEqual(len(bars),1);self.assertEqual(bars[0]['open'],100);self.assertEqual(bars[0]['close'],159)
        sparse=Reference()
        for i in range(10):sparse.add(minute+i*1000,100,now)
        self.assertEqual(sparse.candles(now),[])
    def test_future_values_and_cross_market_data(self):
        ref=Reference();ref.add(1000000100000,100,1000000000000);self.assertIsNone(ref.latest)
        ref.consume({'type':'cfbenchmarks_value','msg':{'index_id':'ETHUSD_RTI','data':'{}'}});self.assertIsNone(ref.latest)
    def test_fixed_point_orderbook(self):
        book=normalize_book({'orderbook_fp':{'yes_dollars':[['0.4500','2.00']],'no_dollars':[['0.5000','3.00']]}},1000);self.assertEqual(book['yes'],[[.45,2.0]])
        with self.assertRaises(ValueError):normalize_book({'orderbook':{'yes':[[45,2]]}},1000)
    def test_invalid_demo_ticker(self):
        with self.assertRaises(ValueError):payload('UNRELATED','yes',.1,'id')
    def test_uncertain_demo_order_is_not_retried(self):
        from btc_worker.demo import main
        calls=[]
        class FakeAPI:
            def __init__(self,*args):pass
            async def request(self,*args):
                calls.append(args)
                raise TimeoutError()
        with tempfile.TemporaryDirectory() as directory, patch('btc_worker.demo.Kalshi',FakeAPI), patch.dict('os.environ',{'KALSHI_DEMO_API_KEY_ID':'test','KALSHI_DEMO_PRIVATE_KEY':'test'}):
            args=SimpleNamespace(ticker='KXBTC15M-TEST',outcome='yes',limit=.1,submit=True,journal=directory+'/journal.sqlite3')
            with self.assertRaises(SystemExit):asyncio.run(main(args))
            with self.assertRaises(SystemExit):asyncio.run(main(args))
            self.assertEqual(len(calls),1)
            with sqlite3.connect(args.journal) as db:self.assertEqual(db.execute('SELECT state FROM attempts').fetchone()[0],'uncertain')
if __name__=='__main__':unittest.main()
