<?php
/*
  quizsasa_final_infinity.php
  جاهز للعمل على InfinityFree + webhook تلقائي
  - التوكن والـ ADMIN_ID تم وضعهم حسب طلبك
  - وقت ثابت لكل سؤال = 20 ثانية
  - يقبل دفعة Polls (quiz) من الأدمن فقط (forward أو إرسال مباشر)
  - لو Poll فيها correct_option_id يتم حفظها تلقائياً
  - لو Poll اتقُبِضت بدون إجابة (انتهى الوقت) البوت يعرض الإجابة الصحيحة ويرسل السؤال التالي
  - زر 🛑 Stop لإيقاف الاختبار مؤقتًا، زر ▶️ أكمل لاستئنافه
  - تحفظ نتيجة المحاولة الأولى فقط في الترتيب (results.json). محاولات لاحقة محفوظة منفصلاً لكن لا تؤثر على الترتيب.
*/

/* ========== CONFIG ========== */
$API_KEY    = "8073434133:AAENfTt28U92wYBXFAgC5XPdmuhLuAuodHA"; // ضع توكن البوت (أنت طلبته توكن هنا)
define('BOT_TOKEN_CONST', '8073434133:AAENfTt28U92wYBXFAgC5XPdmuhLuAuodHA'); // ثابت للنداءات البسيطة
$ADMIN_ID   = 1489001988; // معرف الأدمن كما أعطيته
$API_BASE   = "https://api.telegram.org/bot".$API_KEY."/";
$DOMAIN_URL = "https://sasa407sobhi.infinityfreeapp.com/quizsasa_final_infinity.php"; // رابط ملفك على InfinityFree
$QUESTION_TIME_SEC = 20; // وقت ثابت لكل سؤال

/* ========== DATA FILES ========== */
$DATA_DIR      = __DIR__ . '/data/';
if (!is_dir($DATA_DIR)) mkdir($DATA_DIR, 0775, true);
$SESSIONS_FILE = $DATA_DIR . 'sessions.json';     // جلسات المستخدمين (state)
$ATTEMPTS_FILE = $DATA_DIR . 'attempts.json';     // محاولات جارية ومؤقتة
$RESULTS_FILE  = $DATA_DIR . 'results.json';      // نتائج أول محاولة (للتصنيف)
$ALL_ATT_FILE  = $DATA_DIR . 'all_attempts.json'; // كل المحاولات (للاحتفاظ)
$MAP_POLLS_FILE= $DATA_DIR . 'polls_map.json';    // poll_id => mapping (attempt,qidx,test_id,chat)
$SUBS_FILE     = $DATA_DIR . 'subjects.json';     // subjects fixed (fallback)

/* ========== FIXED SUBJECTS ========== */
$subjects_fixed = [
    1=>"تصميم بحوث",
    2=>"علم نفس إكلينيكي",
    3=>"علم نفس صناعي",
    4=>"علم نفس مرضي",
    5=>"اضطرابات سلوكية",
    6=>"علم نفس عسكري",
    7=>"سيكولوجية الإبداع"
];

/* init minimal files if missing */
foreach ([$SESSIONS_FILE,$ATTEMPTS_FILE,$RESULTS_FILE,$ALL_ATT_FILE,$MAP_POLLS_FILE,$SUBS_FILE] as $f) {
    if (!file_exists($f)) file_put_contents($f, json_encode([], JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
}

/* ========== JSON helpers with simple locking ========== */
function load_json($path) {
    if (!file_exists($path)) return [];
    $txt = @file_get_contents($path);
    $arr = @json_decode($txt, true);
    return is_array($arr) ? $arr : [];
}
function save_json($path, $data) {
    $tmp = $path . '.tmp';
    file_put_contents($tmp, json_encode($data, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
    rename($tmp, $path);
    return true;
}

/* ========== Telegram helpers ========== */
function api_get($method, $params = []) {
    global $API_BASE;
    $url = $API_BASE . $method;
    if (!empty($params)) $url .= '?' . http_build_query($params);
    $ctx = stream_context_create(['http'=>['timeout'=>10]]);
    return @file_get_contents($url, false, $ctx);
}
function api_post($method, $params = []) {
    global $API_BASE;
    $url = $API_BASE . $method;
    $opts = ['http' => ['method' => 'POST', 'header' => "Content-Type: application/x-www-form-urlencoded\r\n", 'content' => http_build_query($params), 'timeout'=>10]];
    $ctx = stream_context_create($opts);
    return @file_get_contents($url, false, $ctx);
}
function sendMessage($chat_id, $text, $reply_markup = null) {
    $params = ['chat_id'=>$chat_id, 'text'=>$text, 'parse_mode'=>'HTML'];
    if ($reply_markup !== null) $params['reply_markup'] = json_encode($reply_markup, JSON_UNESCAPED_UNICODE);
    return api_post('sendMessage', $params);
}
function sendPoll($chat_id, $question, $options, $time_seconds, $correct_option_id) {
    $params = [
        'chat_id'=>$chat_id,
        'question'=>$question,
        'options'=>json_encode(array_values($options), JSON_UNESCAPED_UNICODE),
        'is_anonymous'=>false,
        'type'=>'quiz',
        'open_period'=>intval($time_seconds),
        'correct_option_id'=>intval($correct_option_id)
    ];
    return api_post('sendPoll', $params);
}
function answerCallback($cbid, $text='', $show_alert=false) {
    return api_post('answerCallbackQuery', ['callback_query_id'=>$cbid,'text'=>$text,'show_alert'=>$show_alert]);
}

/* ========== Helpers for subject files ========== */
function safe_subject_filename($subject) {
    $s = mb_strtolower($subject);
    $s = preg_replace('/\s+/u','_',$s);
    $s = preg_replace('/[^a-z0-9_\p{Arabic}]/u','_',$s);
    $s = preg_replace('/_+/','_',$s);
    return __DIR__.'/data/subject_'.trim($s,'_').'.json';
}
function load_tests_for_subject($subject) {
    $f = safe_subject_filename($subject);
    if (file_exists($f)) return load_json($f);
    return [];
}
function save_tests_for_subject($subject, $tests_array) {
    $f = safe_subject_filename($subject);
    return save_json($f, $tests_array);
}

/* ========== Auto-setup webhook (runs on each request first) ========== */
function ensure_webhook_set() {
    global $DOMAIN_URL;
    // check current webhook
    $info_json = api_get('getWebhookInfo');
    $arr = json_decode($info_json, true);
    if (!is_array($arr) || empty($arr['ok'])) {
        // try set
        api_get("setWebhook", ['url'=>$DOMAIN_URL]);
        return;
    }
    $current = $arr['result']['url'] ?? '';
    if (trim($current) !== trim($DOMAIN_URL)) {
        api_get("setWebhook", ['url'=>$DOMAIN_URL]);
    }
}
// run webhook setup (silent)
@ensure_webhook_set();

/* ========== Utilities ========== */
function gen_id($pref='id'){ return $pref.'_'.bin2hex(random_bytes(5)).'_'.round(microtime(true)*1000); }

/* ========== Receive update ========== */
$raw = file_get_contents('php://input');
$update = json_decode($raw, true);
if (!$update) {
    // allow manual cleanup via ?action=cleanup (browser)
    if (php_sapi_name() !== 'cli' && isset($_GET['action']) && $_GET['action']==='cleanup') {
        run_cleanup_timeout();
        echo "Cleanup executed.";
        exit;
    }
    exit;
}

/* Load stores */
$sessions = load_json($SESSIONS_FILE);
$attempts = load_json($ATTEMPTS_FILE);
$results  = load_json($RESULTS_FILE);
$all_atts = load_json($ALL_ATT_FILE);
$polls_map = load_json($MAP_POLLS_FILE);

/* ========== MAIN MESSAGE HANDLER ========== */
if (isset($update['message'])) {
    $message = $update['message'];
    $chat = $message['chat'];
    $chat_id = $chat['id'];
    $from = $message['from'] ?? [];
    $from_id = $from['id'] ?? 0;
    $username = $from['username'] ?? ($from['first_name'] ?? "user_$from_id");
    $text = $message['text'] ?? null;

    // /start
    if ($text === '/start') {
        $rows = [];
        global $subjects_fixed;
        foreach ($subjects_fixed as $n=>$name) $rows[]=[['text'=>$name]];
        array_unshift($rows, [['text'=>'▶️ Start']]);
        sendMessage($chat_id, "أهلاً! اضغط ▶️ Start ثم اختر المادة للبدء.", ['keyboard'=>$rows,'resize_keyboard'=>true]);
        exit;
    }
    if ($text === '▶️ Start') {
        $rows = [];
        global $subjects_fixed;
        foreach ($subjects_fixed as $n=>$name) $rows[]=[['text'=>$name]];
        sendMessage($chat_id, "اختر المادة:", ['keyboard'=>$rows,'resize_keyboard'=>true]);
        exit;
    }

    // choose subject
    if ($text && in_array($text, $subjects_fixed)) {
        $sessions[$chat_id] = ['state'=>'subject_menu','subject'=>$text];
        save_json($SESSIONS_FILE, $sessions);
        $kb = ['keyboard'=>[
            [['text'=>'إضافة دفعة أسئلة']], [['text'=>'عرض الاختبارات']], [['text'=>'🗑️ حذف اختبار']], [['text'=>'🔙 رجوع للخلف']]
        ], 'resize_keyboard'=>true];
        sendMessage($chat_id, "قائمة المادة: <b>{$text}</b>\nاختر:", $kb);
        exit;
    }

    // back
    if ($text === '🔙 رجوع للخلف') {
        unset($sessions[$chat_id]);
        save_json($SESSIONS_FILE, $sessions);
        sendMessage($chat_id, "تم الرجوع. اختر المادة أو اضغط /start:", ['keyboard'=>[['text'=>'▶️ Start']],'resize_keyboard'=>true]);
        exit;
    }

    /* ---------- Add bulk (admin only) ---------- */
    if ($text === 'إضافة دفعة أسئلة') {
        if (!isset($sessions[$chat_id]['subject'])) { sendMessage($chat_id, "اختر مادة أولاً."); exit; }
        if ($from_id != $ADMIN_ID) { sendMessage($chat_id, "❌ فقط الأدمن يمكنه إضافة اختبارات."); exit; }
        // start creation session
        $sessions[$chat_id] = ['state'=>'creating_bulk_polls','subject'=>$sessions[$chat_id]['subject'],'temp'=>['questions'=>[]],'created_at'=>time()];
        save_json($SESSIONS_FILE, $sessions);
        sendMessage($chat_id, "الآن: قم بعمل Forward للـQuiz Polls إلى هذه المحادثة.\nالبوت سيقبل Polls فقط إذا كنت أنت المرسل (Forwarded by you). بعد الانتهاء أرسل 'إنهاء'.");
        exit;
    }

    // inside creating_bulk_polls state
    if (isset($sessions[$chat_id]) && $sessions[$chat_id]['state']==='creating_bulk_polls') {
        if (trim($text) === 'إنهاء') {
            $qarr = $sessions[$chat_id]['temp']['questions'] ?? [];
            if (empty($qarr)) { sendMessage($chat_id, "لم تُحول أية Polls حتى الآن."); exit; }
            // create a test id and save under subject file
            $subject = $sessions[$chat_id]['subject'];
            $tid = gen_id('t');
            $test = ['id'=>$tid,'title'=>"اختبار_".date('Ymd_His'),'subject'=>$subject,'time_per_q'=>$QUESTION_TIME_SEC,'questions'=>$qarr,'created_at'=>time(),'created_by'=>$from_id];
            // load subject tests
            $tests = load_tests_for_subject($subject);
            $tests[$tid] = $test;
            save_tests_for_subject($subject, $tests);
            // also save reference in a global tests list (optional convenience)
            // (we won't rely on it for reading; main storage is per-subject files)
            $sessions[$chat_id] = ['state'=>'subject_menu','subject'=>$subject]; save_json($SESSIONS_FILE,$sessions);
            sendMessage($chat_id, "✅ تم حفظ الاختبار (ID: {$tid}) بنجاح في ملف المادة.", ['keyboard'=>[[['text'=>'🔙 رجوع للخلف']]],'resize_keyboard'=>true]);
            exit;
        }
        // accept poll message from admin
        if (isset($message['poll'])) {
            if ($from_id != $ADMIN_ID) { sendMessage($chat_id, "❌ لا تملك صلاحية إضافة أسئلة — فقط الأدمن يُسمح."); exit; }
            $poll = $message['poll'];
            if (!isset($poll['type']) || $poll['type'] !== 'quiz') {
                sendMessage($chat_id, "⚠️ تم استلام Poll لكنه ليس من نوع <b>quiz</b>. تأكد أنه Quiz."); exit;
            }
            // options and correct_option_id (may be missing when forwarded from other)
            $opts = []; foreach ($poll['options'] as $op) $opts[] = $op['text'] ?? '';
            $corr = isset($poll['correct_option_id']) ? intval($poll['correct_option_id']) : null;
            // if corr missing -> ask admin to pick via inline (we'll create a pending entry in sessions)
            if ($corr === null) {
                // create pending
                $pending_id = gen_id('pending');
                if (!isset($sessions[$chat_id]['pending_polls'])) $sessions[$chat_id]['pending_polls'] = [];
                $sessions[$chat_id]['pending_polls'][$pending_id] = ['question'=>$poll['question'] ?? '','options'=>$opts,'created_at'=>time()];
                save_json($SESSIONS_FILE, $sessions);
                // build inline keyboard
                $inline = [];
                foreach ($opts as $i => $o) {
                    $inline[] = [['text'=>mb_substr($o,0,50),'callback_data'=>"set_correct|{$pending_id}|{$i}"]];
                }
                $inline[] = [['text'=>'إلغاء السؤال','callback_data'=>"cancel_pending|{$pending_id}"]];
                sendMessage($chat_id, "⚠️ لم يتم العثور على الإجابة الصحيحة في هذا Poll.\nاختر الإجابة الصحيحة للسؤال:\n\n<b>{$poll['question']}</b>", ['inline_keyboard'=>$inline]);
                exit;
            } else {
                // store question temporarily in session
                $qobj = ['qid'=>$poll['id'] ?? gen_id('q'),'question'=>$poll['question'] ?? '','options'=>$opts,'correct'=>$corr];
                if (!isset($sessions[$chat_id]['temp'])) $sessions[$chat_id]['temp'] = ['questions'=>[]];
                $sessions[$chat_id]['temp']['questions'][] = $qobj;
                save_json($SESSIONS_FILE, $sessions);
                sendMessage($chat_id, "✅ تم حفظ Poll كسؤال مؤقت. أرسل Poll آخر أو 'إنهاء'.");
                exit;
            }
        } else {
            sendMessage($chat_id, "في وضع استقبال Polls — قم بعمل Forward للـQuiz Polls إلى هنا. عند الانتهاء أرسل 'إنهاء'.");
            exit;
        }
    } // end creating_bulk_polls

    /* ---------- Show tests for subject ---------- */
    if ($text === 'عرض الاختبارات' && isset($sessions[$chat_id]['subject'])) {
        $subject = $sessions[$chat_id]['subject'];
        $tests = load_tests_for_subject($subject);
        if (empty($tests)) { sendMessage($chat_id, "لا توجد اختبارات لهذه المادة.", ['keyboard'=>[['text'=>'🔙 رجوع للخلف']],'resize_keyboard'=>true]); exit; }
        $kb = [];
        foreach ($tests as $tid=>$t) {
            $kb[] = [['text'=>"ابدأ: {$tid}"]];
        }
        $kb[] = [['text'=>'🔙 رجوع للخلف']];
        sendMessage($chat_id, "اختر الاختبار:", ['keyboard'=>$kb,'resize_keyboard'=>true]);
        exit;
    }

    /* ---------- Delete test (admin) ---------- */
    if ($text === '🗑️ حذف اختبار') {
        if (!isset($sessions[$chat_id]['subject'])) { sendMessage($chat_id, "اختر مادة أولاً."); exit; }
        if ($from_id != $ADMIN_ID) { sendMessage($chat_id, "❌ غير مصرح."); exit; }
        $subject = $sessions[$chat_id]['subject'];
        $tests = load_tests_for_subject($subject);
        if (empty($tests)) { sendMessage($chat_id,"لا توجد اختبارات للحذف في هذه المادة.", ['keyboard'=>[['text'=>'🔙 رجوع للخلف']],'resize_keyboard'=>true]); exit; }
        $kb=[];
        foreach ($tests as $tid=>$t) $kb[] = [['text'=>"حذف: {$tid}"]];
        $kb[] = [['text'=>'🔙 رجوع للخلف']];
        sendMessage($chat_id, "اختر الاختبار للحذف:", ['keyboard'=>$kb,'resize_keyboard'=>true]);
        exit;
    }
    if ($text && mb_strpos($text, 'حذف:') === 0) {
        if ($from_id != $ADMIN_ID) { sendMessage($chat_id, "❌ غير مصرح."); exit; }
        if (!preg_match('/^حذف:\s*(.+)$/u', $text, $m)) { sendMessage($chat_id, "تعذر قراءة id."); exit; }
        $tid = $m[1];
        // look through all subjects files to delete
        $deleted = false;
        foreach ($subjects_fixed as $s) {
            $tests = load_tests_for_subject($s);
            if (isset($tests[$tid])) { unset($tests[$tid]); save_tests_for_subject($s,$tests); $deleted = true; }
        }
        if ($deleted) sendMessage($chat_id, "✅ تم حذف الاختبار #{$tid}.", ['keyboard'=>[['text'=>'🔙 رجوع للخلف']],'resize_keyboard'=>true]);
        else sendMessage($chat_id, "الاختبار غير موجود.");
        exit;
    }

    /* ---------- Start test ---------- */
    if ($text && mb_substr($text,0,5) === 'ابدأ:') {
        if (!preg_match('/^ابدأ:\s*(.+)$/u',$text,$m)) { sendMessage($chat_id,"تعذر قراءة id"); exit; }
        $tid = $m[1];
        // find test in subject files
        $found = null; $found_subject = null;
        foreach ($subjects_fixed as $s) {
            $ts = load_tests_for_subject($s);
            if (isset($ts[$tid])) { $found = $ts[$tid]; $found_subject = $s; break; }
        }
        if ($found === null) { sendMessage($chat_id, "اختبار غير موجود."); exit; }
        // create attempt
        $attempt_id = gen_id('a');
        $attempt = [
            'attempt_id'=>$attempt_id,
            'test_id'=>$tid,
            'subject'=>$found_subject,
            'user_id'=>$from_id,
            'username'=>$username,
            'started_at'=>time(),
            'current_q_idx'=>0,
            'answers'=>[],
            'finished'=>false,
            'paused'=>false
        ];
        $attempts = load_json($ATTEMPTS_FILE);
        $attempts[$attempt_id] = $attempt;
        save_json($ATTEMPTS_FILE, $attempts);
        // session
        $sessions[$chat_id] = ['state'=>'in_test','attempt_id'=>$attempt_id,'subject'=>$found_subject];
        save_json($SESSIONS_FILE, $sessions);
        sendMessage($chat_id, "✅ تم بدء الاختبار '{$found['title']}'. سيظهر سؤال واحد كل مرة. لديك {$QUESTION_TIME_SEC} ثانية لكل سؤال.\nيمكنك إيقاف الاختبار مؤقتًا بأي وقت بالضغط على 🛑 Stop.");
        // send first question
        send_question_poll_to_chat($chat_id, $attempt_id, $QUESTION_TIME_SEC);
        exit;
    }

    /* ---------- Stop & Resume controls (for test takers) ---------- */
    if ($text === '🛑 Stop') {
        if (!isset($sessions[$chat_id]['state']) || $sessions[$chat_id]['state'] !== 'in_test') { sendMessage($chat_id, "لا يوجد اختبار جارٍ لإيقافه."); exit; }
        $attempt_id = $sessions[$chat_id]['attempt_id'];
        $attempts = load_json($ATTEMPTS_FILE);
        if (isset($attempts[$attempt_id])) {
            $attempts[$attempt_id]['paused'] = true;
            save_json($ATTEMPTS_FILE, $attempts);
            $sessions[$chat_id]['state'] = 'paused_test';
            save_json($SESSIONS_FILE, $sessions);
            sendMessage($chat_id, "⏸️ تم إيقاف الاختبار مؤقتًا. اضغط ▶️ أكمل لاستئناف من نفس النقطة.");
            exit;
        } else { sendMessage($chat_id,"خطأ: لم أجد محاولتك."); exit; }
    }
    if ($text === '▶️ أكمل') {
        if (!isset($sessions[$chat_id]['state']) || $sessions[$chat_id]['state'] !== 'paused_test') { sendMessage($chat_id, "لا توجد جلسة مؤقتة لاستئنافها."); exit; }
        $attempt_id = $sessions[$chat_id]['attempt_id'];
        $attempts = load_json($ATTEMPTS_FILE);
        if (!isset($attempts[$attempt_id])) { sendMessage($chat_id,"خطأ: المحاولة غير موجودة."); exit; }
        $attempts[$attempt_id]['paused'] = false; save_json($ATTEMPTS_FILE, $attempts);
        $sessions[$chat_id]['state'] = 'in_test'; save_json($SESSIONS_FILE, $sessions);
        sendMessage($chat_id, "▶️ جاري استئناف الاختبار من نفس النقطة.");
        send_question_poll_to_chat($chat_id, $attempt_id, $QUESTION_TIME_SEC);
        exit;
    }

    // default fallback
    sendMessage($chat_id, "لم أفهم الأمر. استخدم /start ثم اختر المادة.", ['keyboard'=>[['text'=>'▶️ Start']],'resize_keyboard'=>true]);
    exit;
} // end message handler

/* ========== POLL_ANSWER handler (user answered a poll) ========== */
if (isset($update['poll_answer'])) {
    $p_ans = $update['poll_answer'];
    $poll_id = $p_ans['poll_id'];
    $user_id = $p_ans['user']['id'];
    $option_ids = $p_ans['option_ids']; // one-element array
    // find mapping
    $polls_map = load_json($MAP_POLLS_FILE);
    if (!isset($polls_map[$poll_id])) {
        // not our poll (ignore)
        exit;
    }
    $map = $polls_map[$poll_id];
    $attempt_id = $map['attempt_id'];
    $qidx = intval($map['qidx']);
    $test_id = $map['test_id'];
    $user_chat = $map['user_chat_id'];

    // load attempt and verify user
    $attempts = load_json($ATTEMPTS_FILE);
    if (!isset($attempts[$attempt_id])) { unset($polls_map[$poll_id]); save_json($MAP_POLLS_FILE,$polls_map); exit; }
    $attempt = $attempts[$attempt_id];
    if ($attempt['user_id'] != $user_id) { exit; } // someone else answered
    // load test
    $tests = load_tests_for_subject($attempt['subject']);
    if (!isset($tests[$test_id])) { unset($polls_map[$poll_id]); save_json($MAP_POLLS_FILE,$polls_map); exit; }
    $test = $tests[$test_id];
    $q = $test['questions'][$qidx];
    $selected = isset($option_ids[0]) ? intval($option_ids[0]) : -1;
    $correct_flag = ($selected === intval($q['correct'])) ? 1 : 0;
    $attempt['answers'][] = ['qidx'=>$qidx,'selected'=>$selected,'correct'=>$correct_flag,'answered_at'=>time(),'timed_out'=>0];
    $attempt['current_q_idx'] = $attempt['current_q_idx'] + 1;
    $attempts[$attempt_id] = $attempt;
    save_json($ATTEMPTS_FILE, $attempts);
    // feedback
    $fb = $correct_flag ? "✅ إجابة صحيحة" : "❌ إجابة خاطئة";
    sendMessage($user_chat, $fb);
    // cleanup poll map
    unset($polls_map[$poll_id]); save_json($MAP_POLLS_FILE,$polls_map);
    // send next or finalize
    if ($attempt['current_q_idx'] >= count($test['questions'])) {
        // finalize
        finalize_attempt($attempt_id, $user_chat);
        exit;
    } else {
        // if paused - do not send next
        if (!empty($attempt['paused'])) { sendMessage($user_chat,"تم إيقاف الاختبار مؤقتًا. اضغط ▶️ أكمل للاستئناف."); exit; }
        send_question_poll_to_chat($user_chat, $attempt_id, $QUESTION_TIME_SEC);
        exit;
    }
}

/* ========== POLL update handler (detect poll closed/timeouts) ========== */
if (isset($update['poll'])) {
    $poll = $update['poll'];
    $poll_id = $poll['id'] ?? null;
    if (!$poll_id) exit;
    // if poll closed and we have it mapped, treat as timeout if user didn't answer
    if (!empty($poll['is_closed'])) {
        $polls_map = load_json($MAP_POLLS_FILE);
        if (!isset($polls_map[$poll_id])) exit;
        $map = $polls_map[$poll_id];
        $attempt_id = $map['attempt_id'];
        $qidx = intval($map['qidx']);
        $user_chat = $map['user_chat_id'];
        // load attempt and test
        $attempts = load_json($ATTEMPTS_FILE);
        if (!isset($attempts[$attempt_id])) { unset($polls_map[$poll_id]); save_json($MAP_POLLS_FILE,$polls_map); exit; }
        $attempt = $attempts[$attempt_id];
        // load test
        $tests = load_tests_for_subject($attempt['subject']);
        if (!isset($tests[$map['test_id']])) { unset($polls_map[$poll_id]); save_json($MAP_POLLS_FILE,$polls_map); exit; }
        $test = $tests[$map['test_id']];
        $q = $test['questions'][$qidx];
        // mark timed out (user didn't answer)
        $attempt['answers'][] = ['qidx'=>$qidx,'selected'=>-1,'correct'=>0,'answered_at'=>time(),'timed_out'=>1];
        $attempt['current_q_idx'] = $attempt['current_q_idx'] + 1;
        $attempts[$attempt_id] = $attempt;
        save_json($ATTEMPTS_FILE, $attempts);
        // notify user with correct answer
        $corr_idx = intval($q['correct']);
        $corr_text = $q['options'][$corr_idx] ?? 'غير معروف';
        sendMessage($user_chat, "⏰ انتهى الوقت. الإجابة الصحيحة هي: <b>{$corr_text}</b>");
        // cleanup map
        unset($polls_map[$poll_id]); save_json($MAP_POLLS_FILE,$polls_map);
        // send next or finalize
        if ($attempt['current_q_idx'] >= count($test['questions'])) {
            finalize_attempt($attempt_id, $user_chat);
            exit;
        } else {
            if (!empty($attempt['paused'])) { sendMessage($user_chat,"تم إيقاف الاختبار مؤقتًا. اضغط ▶️ أكمل للاستئناف."); exit; }
            send_question_poll_to_chat($user_chat, $attempt_id, $QUESTION_TIME_SEC);
            exit;
        }
    }
}

/* ========== CALLBACK handler (for pending polls & marking correct answer) ========== */
if (isset($update['callback_query'])) {
    $cb = $update['callback_query'];
    $cbid = $cb['id'];
    $from = $cb['from'] ?? []; $from_id = $from['id'] ?? 0;
    $data = $cb['data'] ?? '';
    $msg_chat = $cb['message']['chat']['id'] ?? ($cb['message']['chat']['id']??null);

    // set_correct|<pending_id>|<index>
    if (strpos($data, 'set_correct|') === 0) {
        if ($from_id != $ADMIN_ID) { answerCallback($cbid, "غير مصرح"); exit; }
        $parts = explode('|', $data, 3);
        $pending_id = $parts[1] ?? '';
        $index = isset($parts[2]) ? intval($parts[2]) : 0;
        // find pending in sessions
        $sessions = load_json($SESSIONS_FILE);
        $found = false;
        foreach ($sessions as $sChat => $sess) {
            if (isset($sess['pending_polls'][$pending_id])) {
                $pending = $sess['pending_polls'][$pending_id];
                $found = true; $owner_chat = $sChat; break;
            }
        }
        if (!$found) { answerCallback($cbid, "لم أجد السؤال المؤقت"); exit; }
        // add qobj to temp questions
        $qobj = ['qid'=>gen_id('q'),'question'=>$pending['question'],'options'=>$pending['options'],'correct'=>$index];
        if (!isset($sessions[$owner_chat]['temp']['questions'])) $sessions[$owner_chat]['temp']['questions'] = [];
        $sessions[$owner_chat]['temp']['questions'][] = $qobj;
        unset($sessions[$owner_chat]['pending_polls'][$pending_id]);
        save_json($SESSIONS_FILE, $sessions);
        answerCallback($cbid, "✅ تم تعيين الإجابة الصحيحة وحفظ السؤال مؤقتًا.");
        sendMessage($owner_chat, "✅ تم تعيين الإجابة الصحيحة للسؤال وحفظه في الاختبار الجاري. أرسل Poll آخر أو اكتب 'إنهاء'.");
        exit;
    }

    // cancel_pending|<pending_id>
    if (strpos($data, 'cancel_pending|') === 0) {
        if ($from_id != $ADMIN_ID) { answerCallback($cbid, "غير مصرح"); exit; }
        $parts = explode('|', $data, 2);
        $pending_id = $parts[1] ?? '';
        $sessions = load_json($SESSIONS_FILE);
        $found = false;
        foreach ($sessions as $sChat => $sess) {
            if (isset($sess['pending_polls'][$pending_id])) { unset($sessions[$sChat]['pending_polls'][$pending_id]); $found=true; break; }
        }
        save_json($SESSIONS_FILE, $sessions);
        if ($found) { answerCallback($cbid, "✅ تم إلغاء السؤال المؤقت."); sendMessage($msg_chat, "تم إلغاء السؤال المؤقت."); }
        else answerCallback($cbid, "لم أجد السؤال.");
        exit;
    }

    answerCallback($cbid, "تم الاستلام.");
    exit;
}

/* ========== FUNCTIONS ========== */

// send question poll and map it
function send_question_poll_to_chat($chat_id, $attempt_id, $time_seconds) {
    global $ATTEMPTS_FILE, $MAP_POLLS_FILE, $QUESTION_TIME_SEC;
    $attempts = load_json($ATTEMPTS_FILE);
    if (!isset($attempts[$attempt_id])) return false;
    $attempt = $attempts[$attempt_id];
    $tests = load_tests_for_subject($attempt['subject']);
    if (!isset($tests[$attempt['test_id']])) return false;
    $test = $tests[$attempt['test_id']];
    $idx = intval($attempt['current_q_idx']);
    if (!isset($test['questions'][$idx])) return false;
    $q = $test['questions'][$idx];
    // send poll
    $res = sendPoll($chat_id, $q['question'], $q['options'], $time_seconds, $q['correct']);
    $arr = @json_decode($res, true);
    if (!$arr || empty($arr['ok'])) {
        // fallback message
        sendMessage($chat_id, "السؤال ".($idx+1)." من ".count($test['questions']).":\n".$q['question']."\n(الوقت: {$time_seconds} ثانية)");
        return true;
    }
    // map poll id => attempt
    $poll_obj = $arr['result']['poll'] ?? null;
    $poll_id = $poll_obj['id'] ?? null;
    if ($poll_id) {
        $map = load_json($MAP_POLLS_FILE);
        $map[$poll_id] = ['attempt_id'=>$attempt_id,'qidx'=>$idx,'test_id'=>$attempt['test_id'],'user_chat_id'=>$chat_id,'sent_at'=>time()];
        save_json($MAP_POLLS_FILE, $map);
    }
    // record sent time in attempt
    $attempts[$attempt_id]['q_sent_at'] = time();
    save_json($ATTEMPTS_FILE, $attempts);
    return true;
}

// finalize attempt: compute score and save only if first attempt for this user/test
function finalize_attempt($attempt_id, $chat_id_for_notify) {
    global $ATTEMPTS_FILE, $RESULTS_FILE, $ALL_ATT_FILE;
    $attempts = load_json($ATTEMPTS_FILE);
    if (!isset($attempts[$attempt_id])) return false;
    $att = $attempts[$attempt_id];
    $testid = $att['test_id'];
    $total = 0; $corrects = 0;
    // load test to count questions
    $tests = load_tests_for_subject($att['subject']);
    if (isset($tests[$testid])) $total = count($tests[$testid]['questions']);
    foreach ($att['answers'] as $a) if (!empty($a['correct'])) $corrects++;
    $duration = time() - ($att['started_at'] ?? time());
    // save this attempt to all attempts
    $all = load_json($ALL_ATT_FILE);
    $all[] = ['attempt_id'=>$attempt_id,'test_id'=>$testid,'user_id'=>$att['user_id'],'username'=>$att['username'],'score'=>$corrects,'total_questions'=>$total,'duration'=>$duration,'finished_at'=>time()];
    save_json($ALL_ATT_FILE, $all);
    // Check if user already has a saved result for this test in results.json (we keep only the first)
    $results = load_json($RESULTS_FILE);
    $exists = false;
    foreach ($results as $r) if ($r['test_id'] === $testid && $r['user_id'] === $att['user_id']) { $exists = true; break; }
    if (!$exists) {
        $results[] = ['attempt_id'=>$attempt_id,'test_id'=>$testid,'user_id'=>$att['user_id'],'username'=>$att['username'],'score'=>$corrects,'total_questions'=>$total,'duration'=>$duration,'finished_at'=>time()];
        save_json($RESULTS_FILE, $results);
    }
    // remove attempt from ongoing list
    $attempts = load_json($ATTEMPTS_FILE);
    if (isset($attempts[$attempt_id])) unset($attempts[$attempt_id]);
    save_json($ATTEMPTS_FILE, $attempts);
    // notify user
    sendMessage($chat_id_for_notify, "✅ انتهى الاختبار!\nعدد الأسئلة: {$total}\nالإجابات الصحيحة: {$corrects}\nالإجابات الخاطئة: ".($total-$corrects)."\nالوقت: {$duration} ثانية\nملاحظة: النتيجة الأولى محفوظة ولن تتأثر بالمحاولات اللاحقة.");
    return true;
}

// cleanup timed-out polls (fallback) - can be called by visiting ?action=cleanup
function run_cleanup_timeout() {
    global $ATTEMPTS_FILE, $MAP_POLLS_FILE;
    $attempts = load_json($ATTEMPTS_FILE);
    $map = load_json($MAP_POLLS_FILE);
    $now = time();
    $changed = false;
    foreach ($map as $poll_id => $m) {
        // if sent more than QUESTION_TIME_SEC + 3 seconds and still mapped -> consider closed/timeout
        if ($now - intval($m['sent_at']) > (intval($GLOBALS['QUESTION_TIME_SEC']) + 3)) {
            // process as timeout
            $attempt_id = $m['attempt_id'];
            $qidx = intval($m['qidx']);
            $user_chat = $m['user_chat_id'];
            if (!isset($attempts[$attempt_id])) { unset($map[$poll_id]); $changed=true; continue; }
            $attempt = $attempts[$attempt_id];
            // mark timed out
            $attempt['answers'][] = ['qidx'=>$qidx,'selected'=>-1,'correct'=>0,'answered_at'=>$now,'timed_out'=>1];
            $attempt['current_q_idx'] = $attempt['current_q_idx'] + 1;
            $attempts[$attempt_id] = $attempt;
            // notify correct answer if possible
            $tests = load_tests_for_subject($attempt['subject']);
            if (isset($tests[$attempt['test_id']])) {
                $test = $tests[$attempt['test_id']];
                $q = $test['questions'][$qidx] ?? null;
                if ($q) {
                    $corr_text = $q['options'][intval($q['correct'])] ?? 'غير معروف';
                    sendMessage($user_chat, "⏰ انتهى الوقت. الإجابة الصحيحة هي: <b>{$corr_text}</b>");
                }
                // send next question if any and not paused
                if ($attempt['current_q_idx'] >= count($test['questions'])) {
                    finalize_attempt($attempt_id, $user_chat);
                } else {
                    if (empty($attempt['paused'])) send_question_poll_to_chat($user_chat, $attempt_id, $GLOBALS['QUESTION_TIME_SEC']);
                }
            }
            unset($map[$poll_id]);
            $changed = true;
        }
    }
    if ($changed) {
        save_json($ATTEMPTS_FILE, $attempts);
        save_json($MAP_POLLS_FILE, $map);
    }
    return true;
}

/* ========== persist data (safety) ========== */
save_json($SESSIONS_FILE, $sessions);
save_json($ATTEMPTS_FILE, $attempts);
save_json($RESULTS_FILE, $results);
save_json($ALL_ATT_FILE, $all_atts);
save_json($MAP_POLLS_FILE, $polls_map);

/* ========== END OF SCRIPT ========== */
exit;
?>