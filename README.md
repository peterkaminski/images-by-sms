# Images by SMS

## Development Status

**INCOMPLETE**

## Overview

Receive inbound MMS images from Twilio, and distribute to Airtable,
Google Drive, and Slack.

**Images by SMS** is written in Python 3.

## Setting Up The Airtable Bases

(TBD)

## Installation

Clone or download the repository.

```shell
git clone https://github.com/peterkaminski/images-by-sms.git && cd images-by-sms
```

## Script Configuration

Copy `env.sh-template` to `env.sh`, and then replace the dummy API key value with your own Airtable API key and base IDs.

## Python Configuration

To isolate the libraries and versions used by this script, create a venv, then install the libraries.

```shell
virtualenv -p python3 venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run Images by SMS

Load your API key, Airtable bases, and optional local test parameters.

```shell
source env.sh
```

Run the `images-by-sms.py` script.

```shell
./images-by-sms.py
```

## Feedback, Suggestions, Bugs

Feedback is welcome either as Issues or Pull Requests at the [Images by SMS repo](https://github.com/peterkaminski/images-by-sms).

## License

Copyright (c) 2020 Peter Kaminski

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
