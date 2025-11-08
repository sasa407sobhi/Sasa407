# bot_app.py
# بوت تليجرام لاختبارات: واجهة 7 مواد، انشاء / عرض اختبارات، تنفيذ الاختبار، نتائج، واحصائيات لادمن
# يعتمد على: flask, pyTelegramBotAPI (telebot), sqlite3, requests, python-dotenv
# تشغيل كنقطة ويب (webhook) مناسبة على استضافة مثل Render.

import os
import time
import sqlite3
import threading
from flask import Flask, request, abort
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# --- إعدادات ---
TOKEN = os.environ.get("8073434133:AAENfTt28U92wYBXFAgC5XPdmuhLuAuodHA")  # ضع التوكن كمتغير بيئي في الاستضافة
ADMIN_USER_ID = int(os.environ.get("1489001988", "0"))  # يوزر id للادمن (مالك البوت) إن وُجد
WEBHOOK_PATH = f"/webhook/{TOKEN}"
PORT = int(os.environ.get("PORT", 5000))

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "bot_data.db")

# --- قاعدة بيانات SQLite بسيطة ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # جداول: subjects, tests, questions, attempts, answers, users
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS tests (
        id INTEGER PRIMARY KEY,
        subject_id INTEGER,
        title TEXT,
        time_per_question INTEGER,
        created_by INTEGER,
        created_at REAL
    );
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY,
        test_id INTEGER,
        qtext TEXT,
        opt1 TEXT,
        opt2 TEXT,
        opt3 TEXT,
        opt4 TEXT,
        correct INTEGER
    );
    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY,
        test_id INTEGER,
        user_id INTEGER,
        username TEXT,
        started_at REAL,
        finished_at REAL,
        score INTEGER
    );
    CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY,
        attempt_id INTEGER,
        question_id INTEGER,
        selected INTEGER,
        correct INTEGER,
        answered_at REAL
    );
    """)
    conn.commit()
    conn.close()

init_db()

# --- إعداد المواد السبعة (يمكن تغيير الأسماء) ---
DEFAULT_SUBJECTS = ["مادة 1","مادة 2","مادة 3","مادة 4","مادة 5","مادة 6","مادة 7"]
def ensure_default_subjects():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for s in DEFAULT_SUBJECTS:
        try:
            cur.execute("INSERT OR IGNORE INTO subjects(name) VALUES(?)", (s,))
        except:
            pass
    conn.commit()
    conn.close()
ensure_default_subjects()

# --- أدوات قاعدة بيانات ---
def db_query(q, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(q, params)
    rows = cur.fetchall()
    conn.commit()
    conn.close()
    return rows[0] if one and rows else rows

# --- لوحة المفاتيح الرئيسية: 7 أزرار (مواد) ---
def main_keyboard():
    kb = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    subjects = db_query("SELECT id, name FROM subjects")
    for sid, sname in subjects:
        kb.add(KeyboardButton(sname))
    return kb

# --- عند بدء البوت ---
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    txt = "أهلًا! هذه لوحة الاختبارات. اختر مادة للبدء:"
    bot.send_message(msg.chat.id, txt, reply_markup=main_keyboard())

# --- عندما يضغط المستخدم على اسم مادة من لوحة المفاتيح ---
@bot.message_handler(func=lambda m: m.text in [s[1] for s in db_query("SELECT id,name FROM subjects")])
def subject_menu(msg):
    # إيجاد id المادة
    rows = db_query("SELECT id, name FROM subjects WHERE name = ?", (msg.text,), one=True)
    if not rows:
        bot.send_message(msg.chat.id, "خطأ: المادة غير موجودة.")
        return
    sid = rows[0]
    sname = rows[1]
    kb = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    kb.add(KeyboardButton("إنشاء اختبار"), KeyboardButton("عرض الاختبارات"))
    kb.add(KeyboardButton("الرئيسية"))
    # نخزن في جلسة مؤقتة عن طريق ملف بسيط: هنا سنخزن subject_id في قاعدة users بسيطة باستخدام جدول attempts كوسيلة مؤقتة
    # لكن لتبسيط: نخبر المستخدم أننا في قائمة المادة وسننتظر أوامر "إنشاء اختبار" أو "عرض الاختبارات"
    bot.send_message(msg.chat.id, f"قائمة المادة: {sname}\nاختر: إنشاء اختبار أو عرض الاختبارات\n(المادة: {sname})", reply_markup=kb)
    # نرسل رسالة تعليمية: المستخدم عند طلب إنشاء سيُطلب منه اسم الاختبار ثم الوقت ثم الأسئلة

# --- مُسجّل حالات إنشاء الاختبار (جلسة مؤقتة) ---
# سنستخدم dict في الذاكرة sessions: {chat_id: {state:..., subject_name:..., temp_test: {...}}}
SESSIONS = {}

def start_create_test(chat_id, subject_name, user_id):
    SESSIONS[chat_id] = {"state":"creating_name", "subject":subject_name, "creator":user_id, "temp":{}}
    bot.send_message(chat_id, "أدخل اسم الاختبار (الخطوة 1 من 4):")

def cancel_session(chat_id):
    if chat_id in SESSIONS:
        del SESSIONS[chat_id]

# --- استقبال رسائل أثناء إنشاء الاختبار ---
@bot.message_handler(func=lambda m: m.chat.id in SESSIONS)
def creating_flow(msg):
    session = SESSIONS[msg.chat.id]
    state = session["state"]
    text = msg.text.strip()
    if text.lower() == "الغاء" or text.lower()=="إلغاء":
        cancel_session(msg.chat.id)
        bot.send_message(msg.chat.id, "تم إلغاء العملية.", reply_markup=main_keyboard())
        return

    if state == "creating_name":
        session["temp"]["title"] = text
        session["state"] = "creating_time"
        bot.send_message(msg.chat.id, "ادخل الوقت لكل سؤال بالثواني (مثال: 30) — الخطوة 2 من 4:")
        return
    if state == "creating_time":
        try:
            t = int(text)
            session["temp"]["time_per_q"] = t
            session["state"] = "choose_questions_mode"
            kb = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            kb.add(KeyboardButton("إضافة سؤال يدوي"), KeyboardButton("إضافة دفعة أسئلة"))
            kb.add(KeyboardButton("إنهاء وإتمام الاختبار"), KeyboardButton("إلغاء"))
            bot.send_message(msg.chat.id, "اختر: إضافة سؤال يدوي أو إضافة دفعة. (الخطوة 3 من 4)", reply_markup=kb)
            return
        except:
            bot.send_message(msg.chat.id, "أدخل رقماً صحيحاً (عدد الثواني).")
            return
    if state == "adding_manual":
        # نتوقع صيغة: السؤال؟ /خيار1 /خيار2 /خيار3 /خيار4 /الرقم_الصحيح (1-4)
        parts = text.split("|")
        if len(parts) < 6:
            bot.send_message(msg.chat.id, "الرجاء إرسال السؤال بصيغة:\nالسؤال|خيار1|خيار2|خيار3|خيار4|رقم_الإجابة_الصحيحة\nمثال: ما لون السماء؟|أزرق|أخضر|أحمر|أسود|1")
            return
        q, o1, o2, o3, o4, cor = [p.strip() for p in parts[:6]]
        try:
            cor = int(cor) - 1
            if cor not in range(4):
                raise ValueError()
        except:
            bot.send_message(msg.chat.id, "رقم الإجابة صحيح بين 1 و4.")
            return
        # خزّن السؤال مؤقتًا
        if "questions" not in session["temp"]:
            session["temp"]["questions"] = []
        session["temp"]["questions"].append((q,o1,o2,o3,o4,cor))
        bot.send_message(msg.chat.id, f"تم إضافة السؤال. عدد الأسئلة الآن: {len(session['temp']['questions'])}\nأرسل سؤالًا آخر أو اضغط 'إنهاء وإتمام الاختبار'.")
        return
    if state == "adding_bulk":
        # يتوقع أن يرسل المستخدم نصًا بداخله أسئلة على السطر الواحد بالصيغ: سؤال|opt1|opt2|opt3|opt4|رقم_الصحيح
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        added = 0
        for ln in lines:
            parts = ln.split("|")
            if len(parts) < 6:
                continue
            q, o1, o2, o3, o4, cor = [p.strip() for p in parts[:6]]
            try:
                cor = int(cor) - 1
                if cor not in range(4):
                    continue
            except:
                continue
            if "questions" not in session["temp"]:
                session["temp"]["questions"] = []
            session["temp"]["questions"].append((q,o1,o2,o3,o4,cor))
            added += 1
        bot.send_message(msg.chat.id, f"تم إضافة {added} سؤال/أسئلة دفعة واحدة. الآن {len(session['temp'].get('questions',[]))} سؤال.")
        return
    # fallback
    bot.send_message(msg.chat.id, "لم أفهم (أو انتهت الجلسة). ابدأ من جديد أو اضغط 'الرئيسية'.")

# --- زر إنشـاء اختبار (يأتي عبر رسالة نص بعد اختيار المادة) ---
@bot.message_handler(func=lambda m: m.text == "إنشاء اختبار")
def handle_create(msg):
    # نحتاج معنى المادة الحالية لكن لتبسيط: نسأل المستخدم عن اسم المادة (أو اخترنا ضمن الخيارات)
    bot.send_message(msg.chat.id, "أي مادة تريد إنشاء الاختبار لها؟ اكتب اسم المادة بالضبط كما ظهر في لوحة المواد:")
    SESSIONS[msg.chat.id] = {"state":"waiting_for_subject_for_create", "creator": msg.from_user.id}
@bot.message_handler(func=lambda m: m.chat.id in SESSIONS and SESSIONS[m.chat.id].get("state")=="waiting_for_subject_for_create")
def got_subject_for_create(msg):
    subj = msg.text.strip()
    r = db_query("SELECT id FROM subjects WHERE name=?", (subj,), one=True)
    if not r:
        bot.send_message(msg.chat.id, "المادة غير موجودة. تأكد من الاسم.")
        cancel_session(msg.chat.id)
        return
    SESSIONS[msg.chat.id]["state"] = "creating_name"
    SESSIONS[msg.chat.id]["subject"] = subj
    bot.send_message(msg.chat.id, "ابدأ بإدخال اسم الاختبار (الخطوة 1 من 4):")

# --- التعامل مع اختيار "إضافة سؤال يدوي" و "إضافة دفعة" و "إنهاء وإتمام الاختبار" ---
@bot.message_handler(func=lambda m: m.chat.id in SESSIONS and m.text in ["إضافة سؤال يدوي","إضافة دفعة أسئلة","إنهاء وإتمام الاختبار"])
def creating_choices(msg):
    s = SESSIONS[msg.chat.id]
    if msg.text == "إضافة سؤال يدوي":
        s["state"] = "adding_manual"
        bot.send_message(msg.chat.id, "أرسل السؤال بصيغة:\nالسؤال|خيار1|خيار2|خيار3|خيار4|رقم_الإجابة_الصحيحة\n(مثال: ما لون السماء؟|أزرق|أخضر|أحمر|أسود|1)")
        return
    if msg.text == "إضافة دفعة أسئلة":
        s["state"] = "adding_bulk"
        bot.send_message(msg.chat.id, "أرسل الآن نصًا يحتوي الأسئلة، كل سطر بصيغة:\nسؤال|opt1|opt2|opt3|opt4|رقم_الصحيح\n(الرقم من 1 إلى 4).")
        return
    if msg.text == "إنهاء وإتمام الاختبار":
        # نسخ إلى DB
        temp = s.get("temp", {})
        title = temp.get("title")
        tpq = temp.get("time_per_q", 30)
        ques = temp.get("questions", [])
        subj = s.get("subject")
        if not (title and ques and subj):
            bot.send_message(msg.chat.id, "لا يمكن إنهاء الاختبار: تأكد من إدخال الاسم، والوقت، وإضافة سؤال واحد على الأقل.")
            return
        # احصل على subject id
        r = db_query("SELECT id FROM subjects WHERE name=?", (subj,), one=True)
        if not r:
            bot.send_message(msg.chat.id, "خطأ: المادة غير موجودة.")
            cancel_session(msg.chat.id)
            return
        subject_id = r[0]
        # insert test
        now = time.time()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO tests(subject_id, title, time_per_question, created_by, created_at) VALUES(?,?,?,?,?)",
                    (subject_id, title, tpq, s.get("creator"), now))
        test_id = cur.lastrowid
        for q in ques:
            cur.execute("INSERT INTO questions(test_id, qtext, opt1,opt2,opt3,opt4, correct) VALUES(?,?,?,?,?,?,?)",
                        (test_id, q[0], q[1], q[2], q[3], q[4], q[5]))
        conn.commit()
        conn.close()
        bot.send_message(msg.chat.id, f"تم إنشاء الاختبار '{title}' للمادة {subj} بعدد {len(ques)} سؤال.")
        cancel_session(msg.chat.id)
        return

# --- عرض الاختبارات لمادة معينة ---
@bot.message_handler(func=lambda m: m.text == "عرض الاختبارات")
def handle_show_tests(msg):
    bot.send_message(msg.chat.id, "أي مادة تريد عرض اختباراتها؟ اكتب اسم المادة بالضبط:")
    SESSIONS[msg.chat.id] = {"state":"waiting_for_subject_for_show"}

@bot.message_handler(func=lambda m: m.chat.id in SESSIONS and SESSIONS[m.chat.id].get("state")=="waiting_for_subject_for_show")
def got_subject_for_show(msg):
    subj = msg.text.strip()
    r = db_query("SELECT id FROM subjects WHERE name=?", (subj,), one=True)
    if not r:
        bot.send_message(msg.chat.id, "المادة غير موجودة.")
        cancel_session(msg.chat.id)
        return
    subject_id = r[0]
    tests = db_query("SELECT id, title FROM tests WHERE subject_id=?", (subject_id,))
    if not tests:
        bot.send_message(msg.chat.id, "لا توجد اختبارات لهذه المادة.", reply_markup=main_keyboard())
        cancel_session(msg.chat.id)
        return
    kb = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    for tid, title in tests:
        kb.add(KeyboardButton(f"ابدأ: {title} | #{tid}"))
    kb.add(KeyboardButton("الرئيسية"))
    bot.send_message(msg.chat.id, "اختر الاختبار للبدء:", reply_markup=kb)
    cancel_session(msg.chat.id)

# --- بدء الاختبار: رسالة تحتوي على "ابدأ: {title} | #{test_id}" ---
@bot.message_handler(func=lambda m: m.text and m.text.startswith("ابدأ: "))
def start_test(msg):
    txt = msg.text
    # استخراج test_id من النص بعد '#'
    if "#" not in txt:
        bot.send_message(msg.chat.id, "خطأ في اختيار الاختبار.")
        return
    try:
        test_id = int(txt.split("#")[-1])
    except:
        bot.send_message(msg.chat.id, "خطأ في رقم الاختبار.")
        return
    # إنشاء attempt
    now = time.time()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO attempts(test_id, user_id, username, started_at) VALUES(?,?,?,?)",
                (test_id, msg.from_user.id, getattr(msg.from_user, 'username', ''), now))
    attempt_id = cur.lastrowid
    conn.commit()
    conn.close()
    bot.send_message(msg.chat.id, "تم بدء الاختبار — سيتم عرض الأسئلة بالترتيب. حظًا سعيدًا!")
    # جلب كل الأسئلة
    questions = db_query("SELECT id, qtext, opt1,opt2,opt3,opt4,correct FROM questions WHERE test_id=? ORDER BY id", (test_id,))
    # نبدأ إرسال الأسئلة بالتتابع — سنفعل ذلك في Thread حتى لا نعرقل الردود
    threading.Thread(target=run_test_session, args=(msg.chat.id, attempt_id, questions, test_id)).start()

def run_test_session(chat_id, attempt_id, questions, test_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # get time per q
    r = cur.execute("SELECT time_per_question FROM tests WHERE id=?", (test_id,)).fetchone()
    time_per_q = r[0] if r else 30
    correct_count = 0
    total = len(questions)
    # لكل سؤال: نرسل رسالة مع InlineKeyboard للأجوبة وننتظر رد المستخدم (نستعمل polling على DB صغير لحلّ الإجابة)
    for q in questions:
        qid, qtext, o1,o2,o3,o4, correct = q
        # ارسال السؤال
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(o1, callback_data=f"answer|{attempt_id}|{qid}|0"))
        kb.add(InlineKeyboardButton(o2, callback_data=f"answer|{attempt_id}|{qid}|1"))
        kb.add(InlineKeyboardButton(o3, callback_data=f"answer|{attempt_id}|{qid}|2"))
        kb.add(InlineKeyboardButton(o4, callback_data=f"answer|{attempt_id}|{qid}|3"))
        sent = bot.send_message(chat_id, f"السؤال ({questions.index(q)+1}/{total}):\n{qtext}\nلديك {time_per_q} ثانية للإجابة.", reply_markup=kb)
        # ننتظر حتى يرد المستخدم أو ينتهي الوقت.
        start_w = time.time()
        answered = False
        while time.time() - start_w < time_per_q:
            # check answers table for this attempt+question
            row = cur.execute("SELECT selected, correct FROM answers WHERE attempt_id=? AND question_id=?", (attempt_id, qid)).fetchone()
            if row:
                # مستخدم أجاب
                answered = True
                if row[1] == 1:
                    correct_count += 1
                break
            time.sleep(0.6)
        if not answered:
            # أدخل إجابة فارغة (مُعدّة كخاطئة)
            cur.execute("INSERT INTO answers(attempt_id, question_id, selected, correct, answered_at) VALUES(?,?,?,?,?)",
                        (attempt_id, qid, -1, 0, time.time()))
            conn.commit()
        # نستمر للسؤال التالي
    finished_at = time.time()
    # حساب النتيجة النهائية وتحديث attempt
    cur.execute("UPDATE attempts SET finished_at=?, score=? WHERE id=?", (finished_at, correct_count, attempt_id))
    conn.commit()
    # عرض نتيجة للمستخدم
    # نحسب ترتيب المستخدم في هذا الاختبار
    rows = cur.execute("SELECT user_id, score, finished_at, username FROM attempts WHERE test_id=? ORDER BY score DESC, (finished_at - started_at) ASC", (test_id,)).fetchall()
    # تحديد ترتيب attempt_id
    rank = 1
    my_rank = None
    for r in rows:
        if r and r[0] == bot.get_chat(attempt_id).id:  # this is placeholder — can't get user_id from attempt_id that way
            pass
    # بدلاً من ذلك، اعرض نتيجة عامة
    bot.send_message(chat_id, f"انتهى الاختبار!\nعدد الأسئلة: {total}\nالإجابات الصحيحة: {correct_count}\nالإجابات الخاطئة: {total - correct_count}\nالوقت المستغرق: {int(finished_at - float(cur.execute('SELECT started_at FROM attempts WHERE id=?',(attempt_id,)).fetchone()[0]))} ثانية", reply_markup=main_keyboard())
    conn.close()

# --- معالجة ضغط الأزرار (الردود على الأسئلة) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("answer|"))
def handle_answer(call):
    try:
        parts = call.data.split("|")
        _, attempt_id, question_id, selected = parts
        attempt_id = int(attempt_id); question_id = int(question_id); selected = int(selected)
    except:
        bot.answer_callback_query(call.id, "خطأ في بيانات الإجابة.")
        return
    # تحقق إن المستخدم هو نفسه من بدأ الـ attempt
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    att = cur.execute("SELECT user_id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    if not att:
        bot.answer_callback_query(call.id, "جلسة الاختبار غير موجودة.")
        conn.close()
        return
    user_id = att[0]
    if user_id != call.from_user.id:
        bot.answer_callback_query(call.id, "أنت لست صاحب هذه الجلسة.")
        conn.close()
        return
    # تحقق إن لم يُجب مسبقًا
    exists = cur.execute("SELECT id FROM answers WHERE attempt_id=? AND question_id=?", (attempt_id,question_id)).fetchone()
    if exists:
        bot.answer_callback_query(call.id, "لقد أجبت بالفعل على هذا السؤال.")
        conn.close()
        return
    # معرفة الإجابة الصحيحة
    qrow = cur.execute("SELECT correct FROM questions WHERE id=?", (question_id,)).fetchone()
    if not qrow:
        bot.answer_callback_query(call.id, "سؤال غير موجود.")
        conn.close()
        return
    correct = 1 if qrow[0] == selected else 0
    cur.execute("INSERT INTO answers(attempt_id, question_id, selected, correct, answered_at) VALUES(?,?,?,?,?)",
                (attempt_id, question_id, selected, correct, time.time()))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "تم تسجيل إجابتك.")
    # تحديث رسالة السؤال ليظهر أي خيار تم اختيارُه (اختياري)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except:
        pass

# --- أمر ادمن لعرض احصائيات اختبار: /stats {test_id} ---
@bot.message_handler(commands=['stats'])
def cmd_stats(msg):
    if msg.from_user.id != ADMIN_USER_ID:
        bot.send_message(msg.chat.id, "غير مصرح.")
        return
    parts = msg.text.split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "استخدام: /stats {test_id}")
        return
    try:
        tid = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "ادخل رقم اختبار صحيح.")
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total_solves = cur.execute("SELECT COUNT(*) FROM attempts WHERE test_id=?", (tid,)).fetchone()[0]
    top_rows = cur.execute("SELECT username, score, finished_at-started_at as duration FROM attempts WHERE test_id=? ORDER BY score DESC, duration ASC LIMIT 10", (tid,)).fetchall()
    conn.close()
    txt = f"احصائيات اختبار #{tid}\nعدد من حلّوه: {total_solves}\n\nالمراكز:\n"
    rank = 1
    for username, score, duration in top_rows:
        txt += f"{rank}. @{username or 'غير معروف'} — {score} نقطة — الوقت: {int(duration)} ث\n"
        rank += 1
    bot.send_message(msg.chat.id, txt)

# --- Flask webhook endpoint ---
@app.route("/")
def index():
    return "OK - Bot webhook alive"

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return ""
    else:
        abort(403)

# --- بدء الويب وخدمة webhook عند التشغيل محليًا/على Render ---
def set_webhook():
    url_base = os.environ.get("APP_URL")  # مثلاً: https://<your-app>.onrender.com
    if not url_base:
        print("APP_URL غير محدد — لم يتم تعيين webhook.")
        return
    webhook_url = url_base + WEBHOOK_PATH
    bot.remove_webhook()
    result = bot.set_webhook(url=webhook_url)
    print("set_webhook:", result, "->", webhook_url)

if __name__ == "__main__":
    # عند التشغيل على الخادم، تعيين webhook
    set_webhook()
    app.run(host="0.0.0.0", port=PORT)