#!/usr/bin/env python

# PyPI
from airtable import Airtable # pip install airtable-python-wrapper
from flask import Flask, request # pip install flask
from twilio.twiml.messaging_response import MessagingResponse # pip install twilio
from pydrive.auth import GoogleAuth # pip install PyDrive
from pydrive.drive import GoogleDrive # pip install PyDrive
from slack import WebClient # pip install slackclient
from slack.errors import SlackApiError # pip install slackclient
import pendulum # pip install pendulum

# Python
from base64 import b64decode, b64encode
from random import SystemRandom
import hashlib
import hmac
import logging
import os
import re
import requests
import traceback
import urllib.request

# configure logging right away (especially before Flask)
LOGLEVEL = os.environ.get('IMAGES_BY_SMS_LOGLEVEL', 'INFO').upper()
logging.basicConfig(level=LOGLEVEL, format='%(asctime)s - %(levelname)s - %(message)s')

# When using logging,basicConfig(), the following is needed for PyDrive. See:
# * https://github.com/googleapis/google-api-python-client/issues/299
# * https://github.com/googleapis/google-api-python-client/issues/703
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

# get auth keys from environment
airtable_api_key = os.environ['AIRTABLE_API_KEY']
airtable_base_phoso = os.environ['AIRTABLE_BASE_PHOSO']
airtable_base_images_by_sms = os.environ['AIRTABLE_BASE_IMAGES_BY_SMS']

# set up Airtable connections
messages_table = Airtable(airtable_base_phoso, 'Messages', api_key=airtable_api_key)
photos_table = Airtable(airtable_base_phoso, 'Photos', api_key=airtable_api_key)
senders_table = Airtable(airtable_base_phoso, 'Senders', api_key=airtable_api_key)
chapters_table = Airtable(airtable_base_images_by_sms, 'Chapter Setup', api_key=airtable_api_key)

# set up Google Drive connection
gauth = GoogleAuth()
gdrive = GoogleDrive(gauth)

# set up Slack connection
slack_client = WebClient(token=os.environ["SLACK_API_TOKEN"])

def create_sender_id(recipient, sender):
    hash = hmac.digest(recipient.encode(), sender.encode(), 'sha256')
    hash = b64encode(hash).decode('utf-8').upper()
    return re.sub(r'[^A-Z]', '', hash)[:8]

def assemble_filename(data, chapter_abbreviation, date_received_local):
    # get local date and time
    yyyy_mm_dd = date_received_local.strftime('%Y-%m-%d')
    hhmm = date_received_local.strftime('%H%M')

    # get two random digits
    random_digits = SystemRandom().randint(0,99)

    # assemble filename
    return '{}_{}_{}_{}_{}'.format(yyyy_mm_dd, data['Sender'], hhmm, random_digits, chapter_abbreviation)

def find_or_insert(table, field, data):
    record = table.match(field, data[field])
    if len(record) == 0:
        record = table.insert(data)
    return record['id']

def post_to_airtable(data):
    logging.info('Entering post_to_airtable().')
    # get or set sender_record_id
    sender_record_id = find_or_insert(senders_table, 'ID', {'ID': data['Sender']})
    del data['Sender']  # don't need field in data anymore

    # save message, get message record ID
    message_data = {
        'Chapter':'NYI',
        'Sender':[sender_record_id],
        'Text':data['Message Body']
    }

    # save photo to table
    photos_table.insert({
        'Photo': data['Photo'],
        'Filename': data['Filename'],
        'Message': [messages_table.insert(message_data)['id']]
    })
    logging.info('Exiting post_to_airtable().')

def post_to_gdrive(data, filename, folder):
    logging.info('Entering post_to_gdrive().')
    file = gdrive.CreateFile({
        'title': data['Filename'] + '.png',
        'parents': [{'id':folder}]
    })
    file.SetContentFile(filename)
    file.Upload()
    logging.info('Exiting post_to_gdrive().')

def post_to_slack(data, chapter_slack_channel):
    logging.info('Entering post_to_slack().')
    try:
      response = slack_client.chat_postMessage(
          channel=chapter_slack_channel,
          blocks=[
              {
                  'type': 'section',
                  'text': {
                      'type': 'plain_text',
                      'text': data['Message Body']
                  }
              },
              {
                  'type': 'image',
                  'image_url': data['Photo'][0]['url'],
                  'alt_text': 'Image from SMS sender'
              }
          ]
      )
    except SlackApiError as e:
        print(e.response["error"])
    logging.info('Exiting post_to_slack().')

def handle_photo(data):
    logging.info('Entering handle_photo().')
    # get date received in UTC
    date_received = pendulum.now()

    # get sender ID from to, from
    data['Sender'] = create_sender_id(data['To Phone'], data['From Phone'])

    # get chapter data
    chapter_row = chapters_table.match('SMS Phone Number', data['To Phone'])
    chapter_timezone = chapter_row['fields']['Timezone']
    chapter_gdrive_folder = chapter_row['fields']['Google Drive Folder']
    chapter_slack_channel = chapter_row['fields']['Slack Channel']

    # assemble filename
    data['Filename'] = assemble_filename(
        data,
        chapter_row['fields']['City Name Abbreviation'],
        date_received.in_timezone(chapter_timezone)
    )

    # retrieve photo from URL
    url = data['Photo'][0]['url']
    logging.info('Retrieving photo from <{}>.'.format(url))
    request = requests.get(url, allow_redirects=True)
    logging.info('Final URL after redirects: <{}>.'.format(request.url))
    tmp_file_path, headers = urllib.request.urlretrieve(request.url)

    # post the message to the various destinations
    try:
        post_to_airtable(data)
    except Exception:
        traceback.print_exc()
    try:
        post_to_gdrive(data, tmp_file_path, chapter_gdrive_folder)
    except Exception:
        traceback.print_exc()
    try:
        post_to_slack(data, chapter_slack_channel)
    except Exception:
        traceback.print_exc()

    # delete local copy of photo
    os.remove(tmp_file_path)
    logging.info('Exiting handle_photo().')

def main():
    logging.info('Entering main().')
    data = {
        'Message Body': os.environ['MESSAGE_BODY'],
        'To Phone': os.environ['TO_PHONE'],
        'From Phone': os.environ['FROM_PHONE'],
        'Photo': [{'url': os.environ['MEDIA_URL']}]
    }
    handle_photo(data)
    logging.info('Exiting main().')

app = Flask(__name__)

@app.route("/images-by-sms", methods=['GET', 'POST'])
def webhook_images_by_sms():

    logging.info('Entering webhook_images_by_sms().')
    try:
        # Start our response
        resp = MessagingResponse()

        # set up data dict from form data
        data = {
            'Message Body': request.form['Body'],
            'To Phone': request.form['To'],
            'From Phone': request.form['From']
        }

        # add first photo if it exists
        if 'MediaUrl0' in request.form:
            data['Photo'] = [{'url': request.form['MediaUrl0']}]

        # TODO: support multiple photos
        handle_photo(data)

        # respond
        resp.message(os.environ.get('IMAGES_BY_SMS_RESPONSE', "Message received!"))

        # send response
        return str(resp)
    except Exception as e:
        print(e)
        return ''
    logging.info('Exiting webhook_images_by_sms().')

if __name__ == "__main__":
    if 'TO_PHONE' in os.environ:
        exit(main())
    else:
        port = os.environ.get('IMAGES_BY_SMS_PORT', 8000)
        app.run(host='0.0.0.0', port=port, debug=True)
