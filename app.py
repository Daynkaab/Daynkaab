import os
import json
import requests
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from supabase import create_client, Client
from groq import Groq

# Load environment configs
load_dotenv()

app = FastAPI()

# Clients Initialization
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Fetch GreenAPI Keys from your dashboard setup
GREEN_INSTANCE = os.getenv("GREEN_INSTANCE_ID")
GREEN_TOKEN = os.getenv("GREEN_API_TOKEN")
SHOPKEEPER_PHONE = os.getenv("SHOPKEEPER_PHONE") # Your personal WhatsApp number with '@c.us' at the end

def parse_messy_somali(raw_text):
    system_instruction = """
    You are an AI data extractor for a shopkeeper ledger app named Daynkaab.
    The shopkeeper will write transaction updates in informal, messy Somali text.
    Your job is to read the text and extract exactly three pieces of information:
    1. "customer_name": The name of the customer (Capitalize it).
    2. "action": Choose exactly one: 'add_debt' or 'record_payment'.
    3. "amount": The pure integer/number value of money involved.

    Somali Hints for Actions:
    - 'deyn', 'ku qor', 'qaaday', 'lagu leeyahay' means 'add_debt'
    - 'bixiyay', 'soo celiyay', 'ka jar', 'hiir' means 'record_payment'

    Return ONLY a valid JSON object. Do not include any extra text.
    """
    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": raw_text}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(completion.choices[0].message.content)

def update_ledger(parsed_data):
    name = parsed_data["customer_name"]
    action = parsed_data["action"]
    amount = parsed_data["amount"]
    
    response = supabase.table("daynkaab_ledger").select("*").eq("customer_name", name).execute()
    existing_records = response.data
    
    if existing_records:
        current_balance = existing_records[0]["amount_owed"]
        new_balance = current_balance + amount if action == "add_debt" else current_balance - amount
        supabase.table("daynkaab_ledger").update({"amount_owed": new_balance}).eq("customer_name", name).execute()
        return f"🔄 Updated {name}! Previous balance: ${current_balance}. New Balance: ${new_balance}"
    else:
        initial_balance = amount if action == "add_debt" else -amount
        supabase.table("daynkaab_ledger").insert({"customer_name": name, "amount_owed": initial_balance}).execute()
        return f"✅ Created new profile for {name} with an initial balance of ${initial_balance}"

def send_whatsapp_reply(chat_id, text_message):
    """Sends a WhatsApp text message reply back using GreenAPI"""
    url = f"https://green-api.com{GREEN_INSTANCE}/sendMessage/{GREEN_TOKEN}"
    payload = {"chatId": chat_id, "message": text_message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending WhatsApp: {e}")
@app.get("/")
def home():
    return {"status": "Daynkaab live cloud engine is running!"}
@app.post("/webhook")
async def receive_whatsapp(request: Request):
    """Acts as the endpoint receiver for GreenAPI notifications"""
    data = await request.json()
    
    # Check if the notification contains a text message received event
    if data.get("typeWebhook") == "incomingMessageReceived":
        sender_data = data.get("senderData", {})
        sender_id = sender_data.get("sender", "")  # e.g., '252xxxxxx@c.us'
        
        # Security check: Only process messages coming directly from the shopkeeper
        if SHOPKEEPER_PHONE in sender_id:
            message_data = data.get("messageData", {})
            text_received = message_data.get("textMessageData", {}).get("textMessage", "")
            
            print(f"📨 Live Message Received: '{text_received}'")
            
            # Step A: Parse via Groq AI
            ai_result = parse_messy_somali(text_received)
            
            # Step B: Log into Supabase
            db_status_reply = update_ledger(ai_result)
            print(db_status_reply)
            
            # Step C: Reply to Shopkeeper via WhatsApp
            send_whatsapp_reply(sender_id, db_status_reply)
            
    return {"status": "success"}
