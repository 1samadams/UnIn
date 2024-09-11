import os
import requests
from flask import Flask, render_template, redirect, url_for, session, request
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv
from unittest.mock import patch
import unittest

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# OAuth2 Configuration
MICROSOFT_CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID')
MICROSOFT_CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET')
MICROSOFT_AUTHORIZATION_BASE_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
MICROSOFT_TOKEN_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
MICROSOFT_SCOPE = ['Mail.Read']

LINKEDIN_CLIENT_ID = os.getenv('LINKEDIN_CLIENT_ID')
LINKEDIN_CLIENT_SECRET = os.getenv('LINKEDIN_CLIENT_SECRET')
LINKEDIN_AUTHORIZATION_BASE_URL = 'https://www.linkedin.com/oauth/v2/authorization'
LINKEDIN_TOKEN_URL = 'https://www.linkedin.com/oauth/v2/accessToken'
LINKEDIN_SCOPE = ['r_emailaddress', 'r_liteprofile', 'w_messaging']

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login/microsoft')
def login_microsoft():
    microsoft = OAuth2Session(MICROSOFT_CLIENT_ID, scope=MICROSOFT_SCOPE, redirect_uri=url_for('callback_microsoft', _external=True))
    authorization_url, state = microsoft.authorization_url(MICROSOFT_AUTHORIZATION_BASE_URL)
    session['microsoft_state'] = state
    return redirect(authorization_url)

@app.route('/callback/microsoft')
def callback_microsoft():
    microsoft = OAuth2Session(MICROSOFT_CLIENT_ID, state=session['microsoft_state'], redirect_uri=url_for('callback_microsoft', _external=True))
    token = microsoft.fetch_token(MICROSOFT_TOKEN_URL, client_secret=MICROSOFT_CLIENT_SECRET, authorization_response=request.url)
    session['microsoft_token'] = token
    return redirect(url_for('login_linkedin'))

@app.route('/login/linkedin')
def login_linkedin():
    linkedin = OAuth2Session(LINKEDIN_CLIENT_ID, scope=LINKEDIN_SCOPE, redirect_uri=url_for('callback_linkedin', _external=True))
    authorization_url, state = linkedin.authorization_url(LINKEDIN_AUTHORIZATION_BASE_URL)
    session['linkedin_state'] = state
    return redirect(authorization_url)

@app.route('/callback/linkedin')
def callback_linkedin():
    linkedin = OAuth2Session(LINKEDIN_CLIENT_ID, state=session['linkedin_state'], redirect_uri=url_for('callback_linkedin', _external=True))
    token = linkedin.fetch_token(LINKEDIN_TOKEN_URL, client_secret=LINKEDIN_CLIENT_SECRET, authorization_response=request.url)
    session['linkedin_token'] = token
    return redirect(url_for('unified_inbox'))

def fetch_office365_emails(token, next_page=None):
    headers = {'Authorization': f"Bearer {token}"}
    url = next_page or 'https://graph.microsoft.com/v1.0/me/messages'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    return data.get('value', []), data.get('@odata.nextLink', None)

def fetch_linkedin_messages(token, next_page=None):
    headers = {'Authorization': f"Bearer {token}"}
    url = next_page or 'https://api.linkedin.com/v2/conversations'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    return data.get('elements', []), data.get('paging', {}).get('next', None)

@app.route('/inbox')
def unified_inbox():
    microsoft_token = session.get('microsoft_token')
    linkedin_token = session.get('linkedin_token')
    if not microsoft_token or not linkedin_token:
        return redirect(url_for('index'))

    # Pagination parameters
    office365_next_page = request.args.get('office365_next_page')
    linkedin_next_page = request.args.get('linkedin_next_page')

    try:
        emails, office365_next_page = fetch_office365_emails(microsoft_token['access_token'], office365_next_page)
    except Exception as e:
        emails = []

    try:
        linkedin_messages, linkedin_next_page = fetch_linkedin_messages(linkedin_token['access_token'], linkedin_next_page)
    except Exception as e:
        linkedin_messages = []

    unified = {
        'emails': emails,
        'linkedin_messages': linkedin_messages,
        'office365_next_page': office365_next_page,
        'linkedin_next_page': linkedin_next_page
    }
    return render_template('inbox.html', unified=unified)

# Unit Tests
class TestFetchEmails(unittest.TestCase):
    @patch('requests.get')
    def test_fetch_office365_emails(self, mock_get):
        mock_response = {
            'value': [{'subject': 'Test email'}],
            '@odata.nextLink': 'https://graph.microsoft.com/nextPageLink'
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response
        emails, next_page = fetch_office365_emails('dummy_token')
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0]['subject'], 'Test email')
        self.assertEqual(next_page, 'https://graph.microsoft.com/nextPageLink')

    @patch('requests.get')
    def test_fetch_linkedin_messages(self, mock_get):
        mock_response = {
            'elements': [{'subject': 'Test message'}],
            'paging': {'next': 'https://linkedin.com/nextPage'}
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response
        messages, next_page = fetch_linkedin_messages('dummy_token')
        self.assertEqual(len(messages), 1)
        self.assertEqual(next_page, 'https://linkedin.com/nextPage')

if __name__ == '__main__':
    app.run(debug=True)
