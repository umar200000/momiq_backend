"""Isolated synthetic HTTP load: never connects to an existing server or database."""
import argparse
import base64
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import platform
import secrets
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def seed(server,catalog,accounts,active):
    from PIL import Image
    image=BytesIO();Image.new('RGB',(32,32),'blue').save(image,format='PNG')
    photo=base64.b64encode(image.getvalue()).decode()
    sitter_count=min(100,max(1,accounts//10))
    if active>accounts-sitter_count:raise ValueError('Not enough synthetic customers')
    clients=[]
    with server.db() as con:
        for number in range(accounts):
            uid=f'{number:024x}';account=server.default_account()
            account['profile']={'first':'TEST','last':f'Load {number}','photo':photo}
            if number<sitter_count:account['sitterProfile']={'years':1,'about':'SYNTHETIC LOAD FIXTURE','homePhotos':[photo],'housing':'house'}
            con.execute('INSERT INTO users VALUES(?,?,?,0,?)',(uid,f'998{number:09}',json.dumps(account),server.now()))
            con.execute('INSERT INTO user_roles VALUES(?,?)',(uid,'sitter' if number<sitter_count else 'customer'))
            if number<sitter_count:con.execute('INSERT INTO wallet_accounts VALUES(?,?)',(uid,100000000))
            elif len(clients)<active:
                token=secrets.token_urlsafe(40);clients.append(token)
                con.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,'client',time.time()+3600))
    for number in range(sitter_count):
        uid=f'{number:024x}'
        data={'housing':'house','listings':[{'type':kind,'pets':['cat','dog'],'price':50000,'capacity':1 if kind=='personal' else 5,'active':True,
              'location':{'lat':41.31,'lon':69.24,'address':'TEST Toshkent'}} for kind in catalog.SERVICES]}
        with server.db() as con:catalog.save(con,uid,data,0)
        for service in catalog.SERVICES:
            with server.db() as con:
                revision=catalog.document(con,uid)['_revision']
                con.commit()
                catalog.review(con,uid,service,{'decision':'approve','reason':'SYNTHETIC LOAD ONLY','testOnly':True,'_revision':revision},'admin','local')
    return clients,sitter_count


def percentile(values,quantile):
    return round(sorted(values)[max(0,math.ceil(len(values)*quantile)-1)],2) if values else None


def run(accounts,active,cycles,duration_seconds=0,think_ms=0):
    with tempfile.TemporaryDirectory(prefix='momiq-isolated-load-') as directory:
        os.environ.update(MOMIQ_DATA_DIR=directory,MOMIQ_ENV='local',MOMIQ_ALLOW_TEST_LOGIN='1')
        import server
        import catalog
        # The command is a standalone process, with no target URL/DB argument.
        if server.DATA.resolve()!=Path(directory).resolve():raise RuntimeError('Refusing a non-temporary database')
        server.setup();clients,sitters=seed(server,catalog,accounts,active)
        http=server.LocalHTTPServer(('127.0.0.1',0),server.Handler)
        serving=threading.Thread(target=http.serve_forever,daemon=True);serving.start()
        base=f'http://127.0.0.1:{http.server_port}'
        barrier=threading.Barrier(active);measurements=[];lock=threading.Lock()
        def request(token,category,path,data=None):
            if duration_seconds and time.perf_counter()>=deadline:return None
            started=time.perf_counter();status=0;error=None;result=None
            headers={'Authorization':'Bearer '+token}
            body=None
            if data is not None:headers['Content-Type']='application/json';body=json.dumps(data).encode()
            try:
                with urlopen(Request(base+path,data=body,headers=headers),timeout=25) as response:
                    status=response.status;result=json.load(response)
                    if not isinstance(result,dict):raise ValueError('Invalid response shape')
                    if category=='catalog' and not result.get('sitters'):raise ValueError('Empty synthetic catalog')
            except HTTPError as failure:status=failure.code;failure.close()
            except Exception as failure:
                cause=getattr(failure,'reason',failure)
                error=type(cause).__name__+(':'+str(cause.errno) if getattr(cause,'errno',None) is not None else '')
            with lock:measurements.append((category,(time.perf_counter()-started)*1000,status,error))
            if duration_seconds:time.sleep(max(0,min(think_ms/1000,deadline-time.perf_counter())))
            return result if status==200 and not error else None
        def customer(index,token):
            barrier.wait(timeout=30)
            cycle=0
            while (time.perf_counter()<deadline if duration_seconds else cycle<cycles):
                request(token,'catalog','/api/sitters?service=boarding&pet=cat')
                request(token,'profile','/api/me')
                request(token,'bookings','/api/bookings')
                request(token,'inbox','/api/conversations')
                request(token,'notifications','/api/notifications')
                chat=request(token,'open_chat','/api/conversations',{'listingId':f'{index%sitters:024x}:boarding'})
                if chat and chat.get('id'):
                    request(token,'send_chat','/api/conversations/'+chat['id']+'/messages',{'text':'SYNTHETIC LOAD MESSAGE','requestId':f'synthetic-load-message-{index}-{cycle}'})
                cycle+=1
        started=time.perf_counter();deadline=started+duration_seconds
        try:
            with open(os.devnull,'w') as quiet,redirect_stdout(quiet):
                with ThreadPoolExecutor(max_workers=active) as pool:list(pool.map(lambda pair:customer(*pair),enumerate(clients)))
        finally:http.shutdown();http.server_close();serving.join()
        elapsed=time.perf_counter()-started;groups=defaultdict(list)
        for row in measurements:groups[row[0]].append(row)
        result={'createdAt':datetime.now(timezone.utc).isoformat(),'accounts':accounts,'activeCustomers':active,'sitters':sitters,'listings':sitters*3,'cycles':None if duration_seconds else cycles,'mode':'paced_duration' if duration_seconds else 'burst_cycles',
                'durationSeconds':duration_seconds,'thinkMs':think_ms,
                'transport':'Windows/local stdlib ThreadingHTTPServer' if os.name=='nt' else 'local stdlib ThreadingHTTPServer',
                'python':platform.python_version(),'logicalCpus':os.cpu_count(),'elapsedSeconds':round(elapsed,2),'requests':len(measurements),
                'listenBacklog':http.request_queue_size,
                'expectedRequests':None if duration_seconds else active*cycles*7,'requestsPerSecond':round(len(measurements)/elapsed,2),'endpoints':{}}
        for category,rows in groups.items():
            durations=[r[1] for r in rows]
            result['endpoints'][category]={'count':len(rows),'p50Ms':percentile(durations,.5),'p95Ms':percentile(durations,.95),'p99Ms':percentile(durations,.99),
                 'statuses':dict(Counter(str(r[2]) for r in rows)),'transportOrShapeErrors':dict(Counter(r[3] for r in rows if r[3]))}
        with server.db() as con:
            result['database']={'integrity':con.execute('PRAGMA integrity_check').fetchone()[0],'foreignKeyErrors':len(con.execute('PRAGMA foreign_key_check').fetchall()),
                'accounts':con.execute('SELECT COUNT(*) FROM users').fetchone()[0],'chats':con.execute('SELECT COUNT(*) FROM conversations').fetchone()[0],
                'messages':con.execute('SELECT COUNT(*) FROM conversation_messages').fetchone()[0],'bookings':con.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]}
        result['successfulRequests']=sum(status==200 and error is None for _,_,status,error in measurements)
        result['limitations']=[('Synthetic local paced duration, time budget checked before each request; in-flight requests may finish after the window.' if duration_seconds else 'Synthetic local saturation burst; no think time.'),
            'Synchronized customer start; no real mobile network. Throughput elapsed includes HTTP shutdown/drain.',
            'Pre-issued synthetic sessions: does not benchmark SMS, login or TLS.',
            'No booking acceptance, payment, video, reverse proxy, Gunicorn or production host traffic.',
            'This is not proof of production capacity or a service-level guarantee; temporary data is removed.']
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounts',type=int,default=1000)
    parser.add_argument('--active',type=int,default=100)
    parser.add_argument('--cycles',type=int,default=5)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--duration-seconds',type=int,default=0,help='1–300 seconds of paced work, instead of fixed cycles')
    parser.add_argument('--think-ms',type=int,default=0,help='100–10000 ms after each request in duration mode')
    args=parser.parse_args()
    if not 20<=args.accounts<=10000 or not 1<=args.active<=100 or not 1<=args.cycles<=10:parser.error('Use 20–10000 accounts, 1–100 active customers and 1–10 cycles')
    if args.duration_seconds:
        if not 1<=args.duration_seconds<=300 or not 100<=args.think_ms<=10000:parser.error('Duration mode requires 1–300 seconds and 100–10000 ms think time')
    elif args.think_ms:parser.error('Think time requires --duration-seconds')
    if args.output.exists():parser.error('Choose a new report file; existing evidence is never overwritten')
    result=run(args.accounts,args.active,args.cycles,args.duration_seconds,args.think_ms)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as output:json.dump(result,output,indent=2)
    print(json.dumps({key:result[key] for key in ('accounts','activeCustomers','requests','successfulRequests','elapsedSeconds','requestsPerSecond','database')},indent=2))
    expected=result['expectedRequests'] if result['expectedRequests'] is not None else result['requests']
    return 0 if expected>0 and result['successfulRequests']==expected and result['database']['integrity']=='ok' and not result['database']['foreignKeyErrors'] else 1


if __name__=='__main__':sys.exit(main())
