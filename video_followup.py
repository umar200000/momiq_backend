"""Video deadlines are reminders, never findings of neglect or financial events."""
from datetime import timedelta
import booking_care as care
import booking_engine as engine
import notifications
import video_policy as policy


def schedule(con, booking, started):
    if con.execute('SELECT 1 FROM video_schedules WHERE booking_id=?',(booking['id'],)).fetchone():return
    end=engine.parse(booking['ends_at'])
    day=started.astimezone(policy.TASHKENT).date()
    last=end.astimezone(policy.TASHKENT).date()
    # At most 367 days, two rows/day, independent of animal count.
    while day<=last:
        for slot in policy.SLOTS:
            opens,closes=policy.window(day,slot)
            if opens<end and closes>started:
                con.execute('INSERT INTO video_checks(booking_id,day,slot,opens_at,due_at,remind_at) VALUES(?,?,?,?,?,?)',
                    (booking['id'],day.isoformat(),slot,engine.stamp(opens),engine.stamp(closes),
                     engine.stamp(max(started,closes-timedelta(minutes=30)))))
        day+=timedelta(days=1)
    con.execute('INSERT INTO video_schedules VALUES(?,?)',(booking['id'],engine.stamp(started)))


def relevant(con,row):
    # Do not invent obligations after early completion or a disputed service stop.
    if row['status']=='active':return True
    if row['status'] not in ('completed','disputed','cancelled'):return False
    stopped=con.execute("SELECT MIN(created) FROM booking_events WHERE booking_id=? AND status IN ('completed','disputed','cancelled')",(row['booking_id'],)).fetchone()[0]
    return bool(stopped and row['opens_at']<stopped)


def missing(con,row):
    return [r[0] for r in con.execute('SELECT animal_id FROM booking_animals a WHERE booking_id=? AND NOT EXISTS(SELECT 1 FROM booking_videos v WHERE v.booking_id=a.booking_id AND v.pet_id=a.animal_id AND v.day=? AND v.slot=?) ORDER BY animal_id',
                                     (row['booking_id'],row['day'],row['slot']))]


def tick(con,environment,now,limit):
    engine.begin(con);engine.test_gate(con,environment)
    # Upgrade/restart backfill uses persisted two-party activation, not phone time.
    legacy=con.execute("SELECT b.*,MAX(e.created) AS activated FROM bookings b JOIN booking_events e ON e.booking_id=b.id AND e.action='start' AND e.status='active' WHERE NOT EXISTS(SELECT 1 FROM video_schedules s WHERE s.booking_id=b.id) GROUP BY b.id ORDER BY b.seq LIMIT 5").fetchall()
    for row in legacy:schedule(con,row,engine.parse(row['activated']))
    total=0
    for stage,column,cutoff in [('video_missing','checked','due_at'),('video_reminder','reminded','remind_at')]:
        rows=con.execute(f'SELECT c.*,b.customer_id,b.sitter_id,b.status,b.updated FROM video_checks c JOIN bookings b ON b.id=c.booking_id WHERE c.{column}=0 AND c.{cutoff}<=? ORDER BY c.{cutoff},c.booking_id LIMIT ?',
                         (engine.stamp(now),limit)).fetchall()
        for row in rows:
            fresh=engine.parse(row['due_at'])>now-timedelta(days=30)
            notify=relevant(con,row) and fresh and missing(con,row)
            if stage=='video_reminder':notify=notify and row['status']=='active' and now<engine.parse(row['due_at'])
            if notify:
                label='ertalab' if row['slot']=='morning' else 'kechqurun'
                message=(f'{row["day"]} {label}: video hali yuborilmagan. ' +
                         ('Muddat tugashidan oldin video yuboring.' if stage=='video_reminder' else
                          'Sabab yoki favqulodda holatni yozish va yordam xizmatiga murojaat qilish mumkin. Bu xizmat bajarilmaganining tasdig‘i emas; avtomatik jarima yoki qaytim yo‘q.'))
                users=(row['sitter_id'],) if stage=='video_reminder' else (row['sitter_id'],row['customer_id'])
                for user in users:
                    key=f'video-followup:{row["booking_id"]}:{row["day"]}:{row["slot"]}:{stage}:{user}'
                    notifications.publish(con,user,key,'care',row['booking_id'],stage,message)
            con.execute(f'UPDATE video_checks SET {column}=1 WHERE booking_id=? AND day=? AND slot=?',(row['booking_id'],row['day'],row['slot']))
            total+=1
    return total


def overview(con,identity,user,day,now,role):
    rows=con.execute('SELECT c.*,b.status,b.updated FROM video_checks c JOIN bookings b ON b.id=c.booking_id WHERE c.booking_id=? AND c.day=? ORDER BY c.due_at',(identity,day)).fetchall()
    items=[]
    for row in rows:
        if not relevant(con,row):continue
        notes=[{'petId':n['pet_id'],'reason':n['reason'],'emergency':bool(n['emergency']),'created':n['created']} for n in con.execute('SELECT * FROM video_explanations WHERE booking_id=? AND day=? AND slot=? ORDER BY pet_id',(identity,day,row['slot']))]
        items.append({'slot':row['slot'],'dueAt':row['due_at'],'missingPetIds':missing(con,row),
                      'canExplain':role=='sitter' and now>=engine.parse(row['due_at']), 'explanations':notes})
    return items


def explain(con,identity,user,data,now):
    if not isinstance(data,dict) or set(data)!={'petId','day','slot','reason','emergency','requestId'}:raise ValueError('Invalid explanation fields')
    day=care.day_value(data['day']);slot=data['slot'];pet=data['petId']
    if not isinstance(slot,str) or slot not in policy.SLOTS or not isinstance(pet,str) or not 1<=len(pet)<=100 or type(data['emergency']) is not bool:raise ValueError('Invalid explanation')
    reason=care.text(data['reason'],1000,True)
    fingerprint=engine.retry_key(data['requestId'],{'bookingId':identity,**data})
    engine.begin(con)
    booking=care.access(con,identity,user)
    if booking['myRole']!='sitter':raise engine.BookingError(403,'Sababni faqat enaga yozadi')
    prior=con.execute('SELECT * FROM video_explanations WHERE actor=? AND request_id=?',(user,data['requestId'])).fetchone()
    if prior:
        if prior['fingerprint']!=fingerprint:raise engine.BookingError(409,'So‘rov o‘zgargan')
        return {'ok':True}
    row=con.execute('SELECT c.*,b.status,b.updated FROM video_checks c JOIN bookings b ON b.id=c.booking_id WHERE c.booking_id=? AND c.day=? AND c.slot=?',(identity,day,slot)).fetchone()
    if not row or not relevant(con,row) or pet not in missing(con,row):raise engine.BookingError(409,'Yuborilmagan video vazifasi topilmadi')
    if now<engine.parse(row['due_at']):raise engine.BookingError(409,'Video muddati hali tugamagan')
    if con.execute('SELECT 1 FROM video_explanations WHERE booking_id=? AND pet_id=? AND day=? AND slot=?',(identity,pet,day,slot)).fetchone():raise engine.BookingError(409,'Sabab allaqachon saqlangan. Yangilik bo‘lsa yordamga murojaat qiling')
    con.execute('INSERT INTO video_explanations VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,pet,day,slot,user,data['requestId'],fingerprint,reason,int(data['emergency']),engine.stamp(now)))
    con.execute('INSERT INTO audit(actor,action,target,time) VALUES(?,?,?,?)',(user,'video-explanation',engine.encode({'bookingId':identity,'petId':pet,'day':day,'slot':slot,'emergency':data['emergency']}),engine.stamp(now)))
    customer=engine.owned(con,identity,user)['customer_id']
    notifications.publish(con,customer,f'video-explanation:{identity}:{pet}:{day}:{slot}','care',identity,'video_explanation','')
    return {'ok':True}
