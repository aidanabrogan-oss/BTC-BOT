import asyncio, base64, json, time, urllib.request, urllib.error
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, ed25519, rsa

PRODUCTION='https://external-api.kalshi.com'
DEMO='https://external-api.demo.kalshi.co'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Redirect refused for authenticated request')

def http_json(url, method='GET', headers=None, body=None, timeout=10):
    data=None if body is None else json.dumps(body,separators=(',',':')).encode()
    req=urllib.request.Request(url,data=data,method=method,headers={**(headers or {}),'Content-Type':'application/json','Cache-Control':'no-cache','User-Agent':'BTC-BOT-Paper/2.0'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=timeout) as response:
            data=response.read(4_000_001)
            if len(data)>4_000_000: raise RuntimeError('Response too large')
            return json.loads(data)
    except urllib.error.HTTPError as exc:
        # Never include request headers, key material or arbitrary server bodies in logs.
        raise RuntimeError(f'HTTP {exc.code}') from None

class Kalshi:
    def __init__(self,key_id,pem,environment='production'):
        if environment not in ('production','demo'): raise ValueError('Unsupported environment')
        self.environment=environment
        self.host=PRODUCTION if environment=='production' else DEMO
        self.key_id=key_id
        self.private_key=serialization.load_pem_private_key(pem.replace('\\n','\n').encode(),password=None)
    def headers(self,method,path):
        timestamp=str(int(time.time()*1000));message=(timestamp+method.upper()+path.split('?')[0]).encode()
        if isinstance(self.private_key,ed25519.Ed25519PrivateKey): sig=self.private_key.sign(message)
        elif isinstance(self.private_key,rsa.RSAPrivateKey): sig=self.private_key.sign(message,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
        else: raise ValueError('Use a Kalshi RSA or Ed25519 private key')
        return {'KALSHI-ACCESS-KEY':self.key_id,'KALSHI-ACCESS-TIMESTAMP':timestamp,'KALSHI-ACCESS-SIGNATURE':base64.b64encode(sig).decode()}
    async def request(self,path,method='GET',body=None):
        method=method.upper()
        if self.environment=='production' and method!='GET': raise PermissionError('Production order writes are disabled in this build')
        if not path.startswith('/trade-api/v2/') or '://' in path or '..' in path: raise ValueError('Invalid Kalshi path')
        return await asyncio.to_thread(http_json,self.host+path,method,self.headers(method,path),body)
