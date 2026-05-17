# Copyright @Arslan-MD
# Updates Channel t.me/arslanmd
from flask import Flask, request, jsonify
from datetime import datetime
import json
from bs4 import BeautifulSoup
import logging
import os
import atexit
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class IVASSMSClient:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.logged_in = False
        self.csrf_token = None
        self.base_url = "https://www.ivasms.com"
        
        # Start playwright and browser
        self._init_browser()
    
    def _init_browser(self):
        """Initialize playwright and launch a persistent browser context."""
        try:
            self.playwright = sync_playwright().start()
            # Use a persistent context to keep cookies/session across requests
            # You can change the user_data_dir to a fixed path to persist login
            user_data_dir = os.path.join(os.getcwd(), "browser_data")
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,   # Set to False for debugging
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
            )
            self.page = self.context.new_page()
            logger.debug("Playwright browser started")
        except Exception as e:
            logger.error(f"Failed to start playwright browser: {e}")
            raise
    
    def load_cookies_from_file_or_env(self, file_path="cookies.json"):
        """Load cookies from JSON file or environment variable."""
        try:
            if os.getenv("COOKIES_JSON"):
                cookies_raw = json.loads(os.getenv("COOKIES_JSON"))
                logger.debug("Loaded cookies from environment variable")
            else:
                with open(file_path, 'r') as file:
                    cookies_raw = json.load(file)
                    logger.debug("Loaded cookies from file")
            
            # Convert to list of dicts with name, value, domain, path
            cookies = []
            if isinstance(cookies_raw, dict):
                for name, value in cookies_raw.items():
                    cookies.append({
                        "name": name,
                        "value": value,
                        "domain": "www.ivasms.com",
                        "path": "/"
                    })
            elif isinstance(cookies_raw, list):
                for cookie in cookies_raw:
                    if 'name' in cookie and 'value' in cookie:
                        cookies.append({
                            "name": cookie['name'],
                            "value": cookie['value'],
                            "domain": "www.ivasms.com",
                            "path": "/"
                        })
            else:
                logger.error("Cookies in unsupported format")
                return None
            return cookies
        except FileNotFoundError:
            logger.error(f"Cookies file {file_path} not found")
            return None
        except json.JSONDecodeError:
            logger.error("Invalid JSON format in cookies")
            return None
        except Exception as e:
            logger.error(f"Error loading cookies: {e}")
            return None

    def login_with_cookies(self, cookies_file="cookies.json"):
        """Set cookies in browser context and navigate to verify login."""
        logger.debug("Attempting to login with cookies")
        cookies = self.load_cookies_from_file_or_env(cookies_file)
        if not cookies:
            logger.error("No valid cookies loaded")
            return False
        
        # Add cookies to context
        try:
            self.context.add_cookies(cookies)
            # Navigate to the SMS received page to check login and extract CSRF
            self.page.goto(f"{self.base_url}/portal/sms/received", timeout=15000)
            self.page.wait_for_load_state("networkidle")
            
            # Check if we are redirected to login (presence of login form)
            if "login" in self.page.url.lower() or "signin" in self.page.url.lower():
                logger.error("Cookies did not maintain login session, redirect to login page")
                return False
            
            # Extract CSRF token from the page
            csrf_input = self.page.query_selector('input[name="_token"]')
            if csrf_input:
                self.csrf_token = csrf_input.get_attribute("value")
                self.logged_in = True
                logger.debug(f"Logged in successfully with CSRF token: {self.csrf_token}")
                return True
            else:
                logger.error("Could not find CSRF token on page")
                # Debug: dump page content
                content = self.page.content()
                logger.error(f"Page content first 2000 chars: {content[:2000]}")
                return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def _post_form(self, url, data, referer=None):
        """Helper to submit a POST form using playwright."""
        try:
            # Set referer if provided
            if referer:
                self.page.set_extra_http_headers({"Referer": referer})
            # Perform the POST request via page.evaluate to get full browser context
            result = self.page.evaluate("""async ([url, data]) => {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: new URLSearchParams(data)
                });
                return await response.text();
            }""", [url, data])
            # Reset headers
            self.page.set_extra_http_headers({})
            return result
        except Exception as e:
            logger.error(f"POST request error: {e}")
            return None

    def check_otps(self, from_date="", to_date=""):
        """Get SMS summary and list of country/number groups."""
        if not self.logged_in:
            logger.error("Not logged in")
            return None
        
        if not self.csrf_token:
            logger.error("No CSRF token available")
            return None
        
        logger.debug(f"Checking OTPs from {from_date} to {to_date}")
        try:
            url = f"{self.base_url}/portal/sms/received/getsms"
            payload = {
                'from': from_date,
                'to': to_date,
                '_token': self.csrf_token
            }
            referer = f"{self.base_url}/portal/sms/received"
            html_content = self._post_form(url, payload, referer)
            
            if html_content:
                soup = BeautifulSoup(html_content, 'html.parser')
                count_sms = soup.select_one("#CountSMS").text if soup.select_one("#CountSMS") else '0'
                paid_sms = soup.select_one("#PaidSMS").text if soup.select_one("#PaidSMS") else '0'
                unpaid_sms = soup.select_one("#UnpaidSMS").text if soup.select_one("#UnpaidSMS") else '0'
                revenue_sms = soup.select_one("#RevenueSMS").text.replace(' USD', '') if soup.select_one("#RevenueSMS") else '0'
                
                sms_details = []
                items = soup.select("div.item")
                for item in items:
                    country_number = item.select_one(".col-sm-4").text.strip()
                    count = item.select_one(".col-3:nth-child(2) p").text.strip()
                    paid = item.select_one(".col-3:nth-child(3) p").text.strip()
                    unpaid = item.select_one(".col-3:nth-child(4) p").text.strip()
                    revenue = item.select_one(".col-3:nth-child(5) p span.currency_cdr").text.strip()
                    sms_details.append({
                        'country_number': country_number,
                        'count': count,
                        'paid': paid,
                        'unpaid': unpaid,
                        'revenue': revenue
                    })
                
                result = {
                    'count_sms': count_sms,
                    'paid_sms': paid_sms,
                    'unpaid_sms': unpaid_sms,
                    'revenue': revenue_sms,
                    'sms_details': sms_details
                }
                logger.debug(f"Retrieved {len(sms_details)} SMS detail records")
                return result
            else:
                logger.error("Failed to get SMS summary")
                return None
        except Exception as e:
            logger.error(f"Error checking OTPs: {e}")
            return None

    def get_sms_details(self, phone_range, from_date="", to_date=""):
        """Get numbers and stats for a specific phone range."""
        if not self.logged_in:
            logger.error("Not logged in")
            return None
        
        logger.debug(f"Fetching SMS details for range: {phone_range}")
        try:
            url = f"{self.base_url}/portal/sms/received/getsms/number"
            payload = {
                '_token': self.csrf_token,
                'start': from_date,
                'end': to_date,
                'range': phone_range
            }
            referer = f"{self.base_url}/portal/sms/received"
            html_content = self._post_form(url, payload, referer)
            
            if html_content:
                soup = BeautifulSoup(html_content, 'html.parser')
                number_details = []
                items = soup.select("div.card.card-body")
                for item in items:
                    phone_number = item.select_one(".col-sm-4").text.strip()
                    count = item.select_one(".col-3:nth-child(2) p").text.strip()
                    paid = item.select_one(".col-3:nth-child(3) p").text.strip()
                    unpaid = item.select_one(".col-3:nth-child(4) p").text.strip()
                    revenue = item.select_one(".col-3:nth-child(5) p span.currency_cdr").text.strip()
                    onclick = item.select_one(".col-sm-4").get('onclick', '')
                    id_number = onclick.split("'")[3] if onclick else ''
                    
                    number_details.append({
                        'phone_number': phone_number,
                        'count': count,
                        'paid': paid,
                        'unpaid': unpaid,
                        'revenue': revenue,
                        'id_number': id_number
                    })
                logger.debug(f"Retrieved {len(number_details)} numbers for range {phone_range}")
                return number_details
            else:
                logger.error(f"Failed to get SMS details for {phone_range}")
                return None
        except Exception as e:
            logger.error(f"Error getting SMS details: {e}")
            return None

    def get_otp_message(self, phone_number, phone_range, from_date="", to_date=""):
        """Get actual OTP message text for a specific phone number."""
        if not self.logged_in:
            logger.error("Not logged in")
            return None
        
        logger.debug(f"Fetching OTP message for {phone_number}")
        try:
            url = f"{self.base_url}/portal/sms/received/getsms/number/sms"
            payload = {
                '_token': self.csrf_token,
                'start': from_date,
                'end': to_date,
                'Number': phone_number,
                'Range': phone_range
            }
            referer = f"{self.base_url}/portal/sms/received"
            html_content = self._post_form(url, payload, referer)
            
            if html_content:
                soup = BeautifulSoup(html_content, 'html.parser')
                message = soup.select_one(".col-9.col-sm-6 p")
                if message:
                    return message.text.strip()
                else:
                    logger.warning(f"No message content found for {phone_number}")
                    return None
            else:
                logger.error(f"Failed to get OTP message for {phone_number}")
                return None
        except Exception as e:
            logger.error(f"Error getting OTP message: {e}")
            return None

    def get_all_otp_messages(self, sms_details, from_date="", to_date="", limit=None):
        """Iterate over all ranges and numbers to collect OTP messages."""
        all_otp_messages = []
        for detail in sms_details:
            phone_range = detail['country_number']
            number_details = self.get_sms_details(phone_range, from_date, to_date)
            if number_details:
                for number_detail in number_details:
                    if limit is not None and len(all_otp_messages) >= limit:
                        logger.debug(f"Reached limit {limit}, stopping")
                        return all_otp_messages
                    phone_number = number_detail['phone_number']
                    otp_message = self.get_otp_message(phone_number, phone_range, from_date, to_date)
                    if otp_message:
                        all_otp_messages.append({
                            'range': phone_range,
                            'phone_number': phone_number,
                            'otp_message': otp_message
                        })
            else:
                logger.warning(f"No number details for range: {phone_range}")
        return all_otp_messages

    def close(self):
        """Clean up playwright resources."""
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.debug("Playwright resources released")

# Flask app setup
app = Flask(__name__)
client = IVASSMSClient()

# Ensure browser is closed when app exits
atexit.register(client.close)

# Initial login attempt
with app.app_context():
    if not client.login_with_cookies():
        logger.error("Failed to initialize client with cookies")

@app.route('/')
def welcome():
    return jsonify({
        'message': 'Welcome to the IVAS SMS API (Playwright version)',
        'status': 'API is alive',
        'endpoints': {
            '/sms': 'Get OTP messages for a specific date (format: DD/MM/YYYY) with optional limit. Example: /sms?date=01/05/2025&limit=10'
        }
    })

@app.route('/sms')
def get_sms():
    date_str = request.args.get('date')
    limit = request.args.get('limit')
    
    if not date_str:
        return jsonify({'error': 'Date parameter is required in DD/MM/YYYY format'}), 400
    
    try:
        parsed_date = datetime.strptime(date_str, '%d/%m/%Y')
        from_date = date_str
        to_date = request.args.get('to_date', '')
        if to_date:
            datetime.strptime(to_date, '%d/%m/%Y')
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use DD/MM/YYYY'}), 400

    if limit:
        try:
            limit = int(limit)
            if limit <= 0:
                return jsonify({'error': 'Limit must be a positive integer'}), 400
        except ValueError:
            return jsonify({'error': 'Limit must be a valid integer'}), 400
    else:
        limit = None

    if not client.logged_in:
        return jsonify({'error': 'Client not authenticated'}), 401
    
    logger.debug(f"Fetching SMS for date range: {from_date} to {to_date or 'empty'} with limit {limit}")
    result = client.check_otps(from_date=from_date, to_date=to_date)
    
    if not result:
        return jsonify({'error': 'Failed to fetch OTP data'}), 500

    otp_messages = client.get_all_otp_messages(
        result.get('sms_details', []),
        from_date=from_date,
        to_date=to_date,
        limit=limit
    )
    
    return jsonify({
        'status': 'success',
        'from_date': from_date,
        'to_date': to_date or 'Not specified',
        'limit': limit if limit is not None else 'Not specified',
        'sms_stats': {
            'count_sms': result['count_sms'],
            'paid_sms': result['paid_sms'],
            'unpaid_sms': result['unpaid_sms'],
            'revenue': result['revenue']
        },
        'otp_messages': otp_messages
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
