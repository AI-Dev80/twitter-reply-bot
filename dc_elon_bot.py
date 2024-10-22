import os
import discord
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from dotenv import load_dotenv

# Enable logging (optional for debugging)
import logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()

# Load OpenAI API key from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Set up the Discord client
intents = discord.Intents.default()
intents.messages = True
client = discord.Client(intents=intents)

# Set up the OpenAI language model
llm = ChatOpenAI(temperature=.5, openai_api_key=OPENAI_API_KEY, model_name='gpt-3.5-turbo')

def generate_response(message_content):
    # Prompt template for AI to respond as Elon Musk
    system_template = """
        You are Elon Musk. Respond with authority, innovation, and unwavering confidence.
        Your words should radiate vision and ambition, sparking curiosity and driving action.
        Lean into your genius and boldness, challenging limits and embracing the future.
        Keep it concise and direct, under 200 characters.
    """
    system_message_prompt = SystemMessagePromptTemplate.from_template(system_template)
    human_message_prompt = HumanMessagePromptTemplate.from_template("{text}")
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    final_prompt = chat_prompt.format_prompt(text=message_content).to_messages()
    
    # Get the response from the LLM
    response = llm(final_prompt).content
    return response

# Event listener for when the bot has connected
@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

# Event listener for new messages
@client.event
async def on_message(message):
    if message.author == client.user:
        return  # Avoid the bot responding to itself

    # Generate and send a response
    response = generate_response(message.content)
    await message.channel.send(response)

# Run the bot with your Discord token
client.run(os.getenv("DISCORD_BOT_TOKEN"))
