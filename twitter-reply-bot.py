import os
import base64
import json
import time
import logging
from datetime import datetime, timedelta
import tweepy
import gspread
from google.oauth2.service_account import Credentials
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from dotenv import load_dotenv
import schedule

# Enable logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()

# Load Twitter API keys from environment variables
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Load OpenAI API key from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Google Sheets Setup
def setup_google_sheets():
    creds_base64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")
    creds_json = base64.b64decode(creds_base64).decode('utf-8')
    creds_data = json.loads(creds_json)
    credentials = Credentials.from_service_account_info(creds_data)
    
    # Authorize Google Sheets API
    client = gspread.authorize(credentials)
    sheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID")).sheet1
    return sheet

# TwitterBot class to manage Twitter interactions and state
class TwitterBot:
    def __init__(self):
        self.twitter_api = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN,
                                         consumer_key=TWITTER_API_KEY,
                                         consumer_secret=TWITTER_API_SECRET,
                                         access_token=TWITTER_ACCESS_TOKEN,
                                         access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
                                         wait_on_rate_limit=True)
        self.sheet = setup_google_sheets()
        self.twitter_me_id = self.get_me_id()
        self.tweet_response_limit = 10
        self.llm = ChatOpenAI(temperature=.5, openai_api_key=OPENAI_API_KEY, model_name='gpt-3.5-turbo')
        self.mentions_found = 0
        self.mentions_replied = 0
        self.mentions_replied_errors = 0

    # Fetch the authenticated user's Twitter ID
    def get_me_id(self):
        try:
            response = self.twitter_api.get_me()
            return response.data.id
        except Exception as e:
            logging.error(f"Error fetching user ID: {e}")
            return None

    # Generate a response using the language model
    def generate_response(self, mentioned_conversation_tweet_text):
        system_template = """
            You are the Supreme Leader of the Democratic People’s Republic of Korea. Your tone must be authoritative, powerful, and diplomatic.
            RESPONSE FORMAT: Keep responses concise and to the point, under 200 characters.
        """
        system_message_prompt = SystemMessagePromptTemplate.from_template(system_template)
        human_message_prompt = HumanMessagePromptTemplate.from_template("{text}")
        chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
        final_prompt = chat_prompt.format_prompt(text=mentioned_conversation_tweet_text).to_messages()
        return self.llm(final_prompt).content

    # Respond to a specific tweet mention
    def respond_to_mention(self, mention, mentioned_conversation_tweet):
        response_text = self.generate_response(mentioned_conversation_tweet.text)
        try:
            response_tweet = self.twitter_api.create_tweet(text=response_text, in_reply_to_tweet_id=mention.id)
            self.mentions_replied += 1
        except Exception as e:
            logging.error(f"Error replying to mention {mention.id}: {e}")
            self.mentions_replied_errors += 1
            return
        
        try:
            self.sheet.append_row([
                str(mentioned_conversation_tweet.id),
                mentioned_conversation_tweet.text,
                response_tweet.data['id'],
                response_text,
                datetime.utcnow().isoformat(),
                mention.created_at.isoformat()
            ])
        except Exception as e:
            logging.error(f"Error logging data to Google Sheet: {e}")
        return True

    # Get the parent tweet text of a mention
    def get_mention_conversation_tweet(self, mention):
        if mention.conversation_id is not None:
            try:
                return self.twitter_api.get_tweet(mention.conversation_id).data
            except Exception as e:
                logging.error(f"Error fetching conversation tweet: {e}")
        return None

    # Get mentions of the authenticated user
    def get_mentions(self):
        now = datetime.utcnow()
        start_time = now - timedelta(minutes=20)
        start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            return self.twitter_api.get_users_mentions(id=self.twitter_me_id,
                                                       start_time=start_time_str,
                                                       expansions=['referenced_tweets.id'],
                                                       tweet_fields=['created_at', 'conversation_id']).data
        except Exception as e:
            logging.error(f"Error fetching mentions: {e}")
            return []

    # Check if we've already responded to a mention
    def check_already_responded(self, mentioned_conversation_tweet_id):
        try:
            records = self.sheet.get_all_records()
            for record in records:
                if record['mentioned_conversation_tweet_id'] == str(mentioned_conversation_tweet_id):
                    return True
        except Exception as e:
            logging.error(f"Error checking previous responses: {e}")
        return False

    # Process mentions and generate responses
    def respond_to_mentions(self):
        mentions = self.get_mentions()
        if not mentions:
            logging.info("No mentions found")
            return
        self.mentions_found = len(mentions)
        for mention in mentions[:self.tweet_response_limit]:
            mentioned_conversation_tweet = self.get_mention_conversation_tweet(mention)
            if (mentioned_conversation_tweet and 
                mentioned_conversation_tweet.id != mention.id and 
                not self.check_already_responded(mentioned_conversation_tweet.id)):
                self.respond_to_mention(mention, mentioned_conversation_tweet)
        return True

    # Main method to execute the bot's job
    def execute_replies(self):
        logging.info(f"Starting Job: {datetime.utcnow().isoformat()}")
        self.respond_to_mentions()
        logging.info(f"Finished Job: {datetime.utcnow().isoformat()}, Found: {self.mentions_found}, Replied: {self.mentions_replied}, Errors: {self.mentions_replied_errors}")

# Schedule the bot to run every 6 minutes
def job():
    logging.info(f"Job executed at {datetime.utcnow().isoformat()}")
    bot = TwitterBot()
    bot.execute_replies()

if __name__ == "__main__":
    schedule.every(1).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)
