#!/usr/bin/env python

# PyPI
from airtable import Airtable # pip install airtable-python-wrapper
from flask import Flask, request # pip install flask
from PIL import Image # pip install Pillow
from pydrive.auth import GoogleAuth # pip install PyDrive
from pydrive.drive import GoogleDrive # pip install PyDrive
from slack import WebClient # pip install slackclient
from slack.errors import SlackApiError # pip install slackclient
from twilio.twiml.messaging_response import MessagingResponse # pip install twilio
import pendulum # pip install pendulum

# Python
from base64 import b64decode, b64encode
from random import SystemRandom
import hashlib
import hmac
import logging
import mimetypes
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

# get date received in UTC
date_received = pendulum.now()

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

def assemble_filename(data)
    # get local date and time
    date_received_local = date_received.in_timezone(data['Chapter Timezone'])
    yyyy_mm_dd = date_received_local.strftime('%Y-%m-%d')
    hhmm = date_received_local.strftime('%H%M')

    # get two random digits
    random_digits = SystemRandom().randint(0,99)

    # get probable filename extension
    extension = mimetypes.guess_extension(data['Content Type'])

    # assemble filename
    return '{}_{}_{}_{}_{}{}'.format(yyyy_mm_dd, data['Sender'], hhmm, random_digits, data['Chapter Abbreviation'], extension)

def find_or_insert(table, field, data):
    record = table.match(field, data[field])
    if len(record) == 0:
        record = table.insert(data)
    return record['id']

def upsert(table, field, data, fields_to_save):
    record = table.match(field, data[field])
    if len(record) == 0:
        data = {k: v for k, v in data.items() if k in fields_to_save}
        record = table.insert(data)
    else:
        record_fields = record['fields']
        # use dictionary unpacking to update `record` with `data`
        data = {**record_fields, **data}
        data = {k: v for k, v in data.items() if k in fields_to_save}
        table.update(record['id'], data)
    return record['id']

def calc_send_long_response(data, long_response_threshold):
    logging.info('Entering calc_send_long_response().')
    sender_record = senders_table.match('ID', data['Sender'])
    if len(sender_record) == 0:
        # set to an arbitrary large number
        llr_interval = 999999999
    else:
        try:
            date_llr = pendulum.parse(sender_record['fields']['Last Long Response'])
        except ValueError:
            date_llr = pendulum.now().subtract(years=1)
        llr_interval = date_received.diff(date_llr).in_minutes()
    logging.info('Last long response interval = {} minutes.'.format(llr_interval))
    logging.info('Exiting calc_send_long_response().')
    if (llr_interval > long_response_threshold):
        # threshold exceeded, use new date
        return True, date_received
    else:
        # threshold not exceeded, use existing date
        return False, date_llr

def post_to_airtable(data, date_llr):
    logging.info('Entering post_to_airtable().')
    # save sender, get sender_record_id
    sender_record_id = upsert(
        senders_table, 'ID', {
            'ID':data['Sender'],
            'Last Long Response':str(date_llr)
        },
        ['ID', 'Last Long Response', 'Messages']
    )

    # save message, get message record ID
    message_data = {
        'Chapter':data['Chapter Name'],
        'Date Received':str(date_received),
        'Sender':[sender_record_id],
        'Text':data['Message Body']
    }

    # save photo to table
    photos_table.insert({
        'Photo': data['Photo'],
        'Width': data['Width'],
        'Height': data['Height'],
        'Filename': data['Filename'],
        'Message': [messages_table.insert(message_data)['id']]
    })
    logging.info('Exiting post_to_airtable().')

def post_to_gdrive(data, filename):
    logging.info('Entering post_to_gdrive().')
    file = gdrive.CreateFile({
        'title': data['Filename'],
        'mimeType': data['Content Type'],
        'parents': [{'id':data['Chapter Google Drive Folder']}]
    })
    file.SetContentFile(filename)
    file.Upload()
    # set to world readable
    file.InsertPermission({
        'type': 'anyone',
        'value': 'anyone',
        'role': 'reader'}
    )
    link=file['alternateLink'].replace('?usp=drivesdk', '')
    logging.info('File link: <{}>.'.format(link))
    logging.info('Exiting post_to_gdrive().')
    return link

def post_to_slack_via_message(data):
    logging.info('Entering post_to_slack_via_message().')
    blocks=[
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<{}|{}> (Google Drive)".format(data['Google Drive Link'], data['Filename'])
            }
        },
        {
            'type': 'image',
            'image_url': data['Photo'][0]['url'],
            'alt_text': 'Image from SMS sender'
        }
    ]
    if len(data['Message Body']):
        blocks.insert(0,
            {
                'type': 'section',
                'text': {
                    'type': 'plain_text',
                    'text': data['Message Body']
                }
            }
        )

    try:
      response = slack_client.chat_postMessage(
          channel=data['Chapter Slack Channel'],
          blocks=blocks
      )
    except SlackApiError as e:
        logging.error("Slack API Error: {}".format(e.response["error"]))
    logging.info('Exiting post_to_slack_via_message().')

def post_to_slack_via_upload(data, filename):
    logging.info('Entering post_to_slack_via_upload().')

    try:
      response = slack_client.conversations_join(
          channel=data['Chapter Slack Channel']
      )
      response = slack_client.files_upload(
          channels=data['Chapter Slack Channel'],
          file=filename,
          title=data['Filename'],
          initial_comment = "{}\n<{}|{}> (Google Drive)".format(data['Message Body'], data['Google Drive Link'], data['Filename'])
      )
    except SlackApiError as e:
        logging.error("Slack API Error: {}".format(e.response["error"]))
    logging.info('Exiting post_to_slack_via_upload().')

def handle_photo(data):
    logging.info('Entering handle_photo().')

    # assemble filename
    data['Filename'] = assemble_filename(data)

    # retrieve photo from URL
    url = data['Photo'][0]['url']
    logging.info('Retrieving photo from <{}>.'.format(url))
    request = requests.get(url, allow_redirects=True)
    logging.info('Final URL after redirects: <{}>.'.format(request.url))
    tmp_file_path, headers = urllib.request.urlretrieve(request.url)

    # get photo size
    data['Width'] = 0
    data['Height'] = 0
    try:
        photo = Image.open(tmp_file_path)
        data['Width'], data['Height'] = photo.size
    except Exception:
        traceback.print_exc()

    # decide whether to send long response or not
    send_long_response, date_llr = calc_send_long_response(data, 60)

    # post the message to the various destinations
    try:
        post_to_airtable(data, date_llr)
    except Exception:
        traceback.print_exc()
    try:
        data['Google Drive Link'] = post_to_gdrive(data, tmp_file_path)
    except Exception:
        traceback.print_exc()
    try:
        post_to_slack_method = 'upload' # set to either 'upload' or 'message'
        if post_to_slack_method == 'upload':
            post_to_slack_via_upload(data, tmp_file_path)
        if post_to_slack_method == 'message':
            post_to_slack_via_message(data)
    except Exception:
        traceback.print_exc()

    # delete local copy of photo
    os.remove(tmp_file_path)
    logging.info('Exiting handle_photo().')
    return send_long_response

def main():
    logging.info('Entering main().')
    data = {
        'Message Body': os.environ['MESSAGE_BODY'],
        'To Phone': os.environ['TO_PHONE'],
        'From Phone': os.environ['FROM_PHONE'],
        'Photo': [{'url': os.environ['MEDIA_URL']}]
    }
    send_long_response = handle_photo(data)
    logging.info('Exiting main().')

app = Flask(__name__)

@app.route("/images-by-sms", methods=['GET', 'POST'])
def webhook_images_by_sms():

    logging.info('----------------------------------------------------------------')
    logging.info('Entering webhook_images_by_sms().')
    try:
        # Log incoming request.form and SmsMessageSid
        logging.debug('Incoming request.form:')
        logging.debug(request.form)
        logging.info('SmsMessageSid: <{}>.'.format(request.form['SmsMessageSid']))

        # Start our response
        resp = MessagingResponse()

        # set up data dict from form data
        data = {
            'Message Body': request.form['Body'],
            'To Phone': request.form['To'],
            'From Phone': request.form['From']
        }

        # get sender ID from to, from
        data['Sender'] = create_sender_id(data['To Phone'], data['From Phone'])

        # get chapter data
        chapter_row = chapters_table.match('SMS Phone Number', data['To Phone'])
        data['Chapter Name'] = chapter_row['fields']['Chapter Name']
        data['Chapter Abbreviation'] = chapter_row['fields']['City Name Abbreviation']
        data['Chapter Timezone'] = chapter_row['fields']['Timezone']
        data['Chapter Google Drive Folder'] = chapter_row['fields']['Google Drive Folder']
        data['Chapter Slack Channel'] = chapter_row['fields']['Slack Channel']

        # handle photos
        send_long_response = False
        for media_index in range(0, request.form['NumMedia']):
            logging.info('Handling photo {}.'.format(media_index))
            data['Photo'] = [{'url': request.form['MediaUrl{}'.format(media_index)]}]
            data['Content Type'] = request.form['MediaContentType{}'.format(media_index)]
            send_long_response |= handle_photo(data)

        # set up response
        if send_long_response:
            logging.info('Sending long response.')
            resp.message(os.environ.get('IMAGES_BY_SMS_LONG_RESPONSE', "Message received!"))
        else:
            logging.info('Sending short response.')
            resp.message(os.environ.get('IMAGES_BY_SMS_SHORT_RESPONSE', "Message received!"))

        # send response
        return str(resp)
    except Exception:
        traceback.print_exc()
        return ''
    logging.info('Exiting webhook_images_by_sms().')

if __name__ == "__main__":
    if 'TO_PHONE' in os.environ:
        exit(main())
    else:
        port = os.environ.get('IMAGES_BY_SMS_PORT', 8000)
        app.run(host='0.0.0.0', port=port, debug=True)
