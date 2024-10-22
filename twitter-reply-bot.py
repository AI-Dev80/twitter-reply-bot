import tweepy
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
import schedule
import time
import os
import logging
from dotenv import load_dotenv

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

# Load Google Sheets credentials and Google Sheet ID
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "kibo-cre.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

# Setup Google Sheets API
def setup_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDENTIALS, scope)
    client = gspread.authorize(creds)
    
    try:
        # Open the Google Sheet using the Google Sheet ID
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
        return sheet
    except Exception as e:
        logging.error(f"Error opening Google Sheet: {e}")
        return None

# TwitterBot class to manage Twitter interactions and state
class TwitterBot:
    def __init__(self):
        # Setup Twitter API client
        self.twitter_api = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN,
                                         consumer_key=TWITTER_API_KEY,
                                         consumer_secret=TWITTER_API_SECRET,
                                         access_token=TWITTER_ACCESS_TOKEN,
                                         access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
                                         wait_on_rate_limit=True)
        
        # Setup Google Sheets
        self.sheet = setup_google_sheets()
        self.twitter_me_id = self.get_me_id()
        self.tweet_response_limit = 10  # Max number of replies to handle at a time
        
        # Initialize OpenAI language model
        self.llm = ChatOpenAI(temperature=.5, openai_api_key=OPENAI_API_KEY, model_name='gpt-3.5-turbo')
        
        # Tracking stats
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
            You are the Supreme Leader of the Democratic People’s Republic of Korea. Your tone must be authoritative, powerful, and diplomatic. You must invoke national strength, resolve, and firm leadership.
            RESPONSE TONE:
            - Assertive, commanding, and formal.
            - Strong phrases such as "in the face of our might" or "no challenge is too great."
            RESPONSE FORMAT:
            - Keep responses concise and to the point, under 200 characters.
        """
        system_message_prompt = SystemMessagePromptTemplate.from_template(system_template)
        human_message_prompt = HumanMessagePromptTemplate.from_template("{text}")
        chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
        final_prompt = chat_prompt.format_prompt(text=mentioned_conversation_tweet_text).to_messages()
        response = self.llm(final_prompt).content
        return response

    # Respond to a specific tweet mention
    def respond_to_mention(self, mention, mentioned_conversation_tweet):
        response_text = self.generate_response(mentioned_conversation_tweet.text)
        try:
            # Create a tweet response
            response_tweet = self.twitter_api.create_tweet(text=response_text, in_reply_to_tweet_id=mention.id)
            self.mentions_replied += 1
        except Exception as e:
            logging.error(f"Error replying to mention {mention.id}: {e}")
            self.mentions_replied_errors += 1
            return
        
        # Log the response in Google Sheets if it was successful
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
                conversation_tweet = self.twitter_api.get_tweet(mention.conversation_id).data
                return conversation_tweet
            except Exception as e:
                logging.error(f"Error fetching conversation tweet: {e}")
                return None
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

# Schedule the bot to run every X minutes
def job():
    logging.info(f"Job executed at {datetime.utcnow().isoformat()}")
    bot = TwitterBot()
    bot.execute_replies()

if __name__ == "__main__":
    # Schedule the job to run every 6 minutes
    schedule.every(6).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)
