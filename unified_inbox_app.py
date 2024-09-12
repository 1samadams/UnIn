# File: unified_inbox_app.py

import os
import requests
import logging
from flask import Flask, render_template, redirect, url_for, session, request, flash, jsonify
from requests_oauthlib import OAuth2Session
from cachetools import TTLCache
from functools import wraps
from dotenv import load_dotenv
from unittest.mock import patch
import unittest

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Logging configuration for error logs
logging.basicConfig(filename='app_errors.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

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

# Cache setup: caching for 5 minutes (300 seconds)
cache = TTLCache(maxsize=100, ttl=300)

def cache_api_response(cache_key):
    """Caching decorator to reduce redundant API calls."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if cache_key in cache and not request.args.get('refresh'):
                return cache[cache_key]
            result = func(*args, **kwargs)
            cache[cache_key] = result
            return result
        return wrapper
    return decorator

@app.route('/')
def inbox():
    return render_template('inbox.html')

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

@cache_api_response('office365_emails')
def fetch_office365_emails(token, next_page=None):
    headers = {'Authorization': f"Bearer {token}"}
    url = next_page or 'https://graph.microsoft.com/v1.0/me/messages'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch Office 365 emails: {e}")
        raise
    data = response.json()
    return data.get('value', []), data.get('@odata.nextLink', None)

@cache_api_response('linkedin_messages')
def fetch_linkedin_messages(token, next_page=None):
    headers = {'Authorization': f"Bearer {token}"}
    url = next_page or 'https://api.linkedin.com/v2/conversations'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch LinkedIn messages: {e}")
        raise
    data = response.json()
    return data.get('elements', []), data.get('paging', {}).get('next', None)

@app.route('/inbox', methods=['GET', 'POST'])
def unified_inbox():
    microsoft_token = session.get('microsoft_token')
    linkedin_token = session.get('linkedin_token')
    if not microsoft_token or not linkedin_token:
        return redirect(url_for('inbox'))

    # Handle search query
    search_query = request.form.get('search_query', '').lower()

    # Handle sorting
    sort_option = request.form.get('sort_option', 'date_desc')

    # Pagination parameters
    office365_next_page = request.args.get('office365_next_page')
    linkedin_next_page = request.args.get('linkedin_next_page')

    try:
        emails, office365_next_page = fetch_office365_emails(microsoft_token['access_token'], office365_next_page)
        if not emails:
            flash('No new emails available.', 'info')
    except Exception as e:
        flash('Failed to retrieve Office 365 emails.', 'danger')
        emails = []

    try:
        linkedin_messages, linkedin_next_page = fetch_linkedin_messages(linkedin_token['access_token'], linkedin_next_page)
        if not linkedin_messages:
            flash('No new LinkedIn messages available.', 'info')
    except Exception as e:
        flash('Failed to retrieve LinkedIn messages.', 'danger')
        linkedin_messages = []

    # Filter emails and messages based on the search query
    if search_query:
        emails = [email for email in emails if search_query in email.get('subject', '').lower()]
        linkedin_messages = [msg for msg in linkedin_messages if search_query in msg.get('subject', '').lower()]

    # Sort emails and LinkedIn messages
    if sort_option == 'subject_asc':
        emails.sort(key=lambda x: x.get('subject', '').lower())
        linkedin_messages.sort(key=lambda x: x.get('subject', '').lower())
    elif sort_option == 'subject_desc':
        emails.sort(key=lambda x: x.get('subject', '').lower(), reverse=True)
        linkedin_messages.sort(key=lambda x: x.get('subject', '').lower(), reverse=True)
    elif sort_option == 'date_asc':
        emails.sort(key=lambda x: x.get('receivedDateTime', ''))
        linkedin_messages.sort(key=lambda x: x.get('created', ''))
    elif sort_option == 'date_desc':
        emails.sort(key=lambda x: x.get('receivedDateTime', ''), reverse=True)
        linkedin_messages.sort(key=lambda x: x.get('created', ''), reverse=True)

    unified = {
        'emails': emails,
        'linkedin_messages': linkedin_messages,
        'office365_next_page': office365_next_page,
        'linkedin_next_page': linkedin_next_page
    }
    return render_template('inbox.html', unified=unified, search_query=search_query, sort_option=sort_option)

@app.route('/loading')
def loading():
    """Simulate a loading page for AJAX loading spinner."""
    return jsonify({'status': 'loading'})

@app.route('/load_more_emails', methods=['GET'])
def load_more_emails():
    """Fetch additional Office 365 emails for infinite scrolling."""
    microsoft_token = session.get('microsoft_token')
    office365_next_page = request.args.get('office365_next_page')
    try:
        emails, next_page = fetch_office365_emails(microsoft_token['access_token'], office365_next_page)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({'emails': emails, 'next_page': next_page})

@app.route('/load_more_linkedin_messages', methods=['GET'])
def load_more_linkedin_messages():
    """Fetch additional LinkedIn messages for infinite scrolling."""
    linkedin_token = session.get('linkedin_token')
    linkedin_next_page = request.args.get('linkedin_next_page')
    try:
        messages, next_page = fetch_linkedin_messages(linkedin_token['access_token'], linkedin_next_page)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({'messages': messages, 'next_page': next_page})

@app.route('/clear_cache')
def clear_cache():
    """Clear the cache manually and refresh the inbox."""
    cache.clear()
    return redirect(url_for('unified_inbox', refresh=True))

# Unit Tests
class TestFetchEmails(unittest.TestCase):
    @patch('requests.get')
    def test_fetch_office365_emails(self, mock_get):
        mock_response = {
            'value': [{'subject': 'Test email', 'receivedDateTime': '2024-01-01T12:00:00Z'}],
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
            'elements': [{'subject': 'Test message', 'created': '2024-01-01T12:00:00Z'}],
            'paging': {'next': 'https://linkedin.com/nextPage'}
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response
        messages, next_page = fetch_linkedin_messages('dummy_token')
        self.assertEqual(len(messages), 1)
        self.assertEqual(next_page, 'https://linkedin.com/nextPage')

if __name__ == '__main__':
    app.run(debug=True)
