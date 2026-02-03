# untis-google-calendar-sync
A short program, that takes your WebUntis timetable into your google calender.

## 1. Clone repository
```bash
git clone https://github.com/MyName-99a/untis-google-calendar-sync.git
```

## 2. Install dependencies and chromium
First install the requirements and then use the command to install chromium
```bash
pip install -r requirements.txt

playwright install chromium
```

## 3. Configuration for your WebUntis account
#### 1. WebUntis Login: Create a ```login.py``` file and fill it out (See login_example.py as example).

### 4. Create a google project to access its API
#### 1. Go to https://console.cloud.google.com/ and create a new Project. Select it.
#### 2. Search at the top for ```Google Calendar API```. Activate it.
#### 3. Go to the ```OAuth consent screen```. Follow the ```First Steps``` there. Choose your Project name, set the mark on external, choose an E-Mail for contacts and accept.
#### 4. Go again (if you left the site) to the ```OAuth consent screen``` and create a ```OAuth client ID```. Choose ```Desktop App``` and the name of the project. Create. Here, download the JSON file and name it ```credentials.json```. Add it to your project folder.
#### 5. When you now start the ```main3.0.py``` you'll be greeted with a Google login site. Use the account you want the calendar to be in. A ```toke.json``` should've been created.
#### 6. Now after 7 days the test phase of your project should be expired. To prevent this publish it now: Go to the ```OAuth consent screen``` and publish the app/project there. If you are being asked to check your project, select no.
#### 7. The script is now read to run. (Maybe run your program again to create a new ```toke.json``` after you set the project to public).

## 4. For automation
I use Cron on Ubuntu to run it every few minutes:

```bash 
# It would run every 4min between 6 and 19 o'clock
*/4 6-19 * * * /path/to/your/venv/bin/python3 /path/to/main3.0.py
```

## Info
When you dont see the publish button. Wait till the 7 days run out and the program runs into a error. Then it should pop-up.