import json
import csv
import os
from datetime import datetime
import requests
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="24/7 AI Receptionist", page_icon="💬", layout="centered")

# 1. Load the business profiles from shops.json
with open("shops.json", "r", encoding="utf-8") as f:
    SHOPS = json.load(f)

# 2. Read the URL parameters (?shop=... and &admin=1)
params = st.query_params
url_shop = params.get("shop", "higher_thought")
if url_shop not in SHOPS:
    url_shop = "higher_thought"

is_admin = params.get("admin", "0") == "1"

# 3. Show the sidebar switcher ONLY if you are in Admin mode (&admin=1)
if is_admin:
    st.sidebar.header("🔧 Demo Control Panel")
    shop_keys = list(SHOPS.keys())
    selected_shop_key = st.sidebar.selectbox(
        "Switch Active Business:",
        shop_keys,
        index=shop_keys.index(url_shop)
    )
    st.sidebar.caption("Tip: Remove &admin=1 from the URL when texting a link to a shop owner.")
else:
    selected_shop_key = url_shop

shop = SHOPS[selected_shop_key]

# Reset chat if you switch shops in the sidebar
if st.session_state.get("active_shop") != selected_shop_key:
    st.session_state.active_shop = selected_shop_key
    st.session_state.messages = [
        {"role": "assistant", "content": f"Hi! Welcome to **{shop['name']}**. How can I help you today?"}
    ]
    st.session_state.turn_count = 0

# 4. Function that saves the lead to CSV and buzzes your phone via ntfy.sh
def save_and_notify_lead(customer_name, phone_number, service_request):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.isfile("leads.csv")
    with open("leads.csv", "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(["Timestamp", "Shop", "Name", "Phone", "Request"])
        writer.writerow([timestamp, shop["name"], customer_name, phone_number, service_request])

    ntfy_topic = st.secrets.get("NTFY_TOPIC", "")
    if ntfy_topic:
        try:
            requests.post(
                f"https://ntfy.sh/{ntfy_topic}",
                data=f"Shop: {shop['name']}\nClient: {customer_name}\nPhone: {phone_number}\nNeed: {service_request}".encode("utf-8"),
                headers={
                    "Title": f"New Lead: {shop['name']}",
                    "Priority": "5",
                    "Tags": "fire,telephone_receiver"
                },
                timeout=5
            )
        except Exception:
            pass

# 5. Define the OpenAI Tool so the AI knows how to extract a lead cleanly
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": "Call this ONLY when the customer has provided their name, phone number, and what service/item they want.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "The customer's name"},
                    "phone_number": {"type": "string", "description": "The customer's phone number"},
                    "service_request": {"type": "string", "description": "The service, appointment time, or item requested"}
                },
                "required": ["customer_name", "phone_number", "service_request"]
            }
        }
    }
]

# 6. Draw the Shop Header on screen
st.title(shop["name"])
st.caption(f"📍 {shop['location']}  |  🕒 {shop['hours']}")

with st.expander("📋 View Services & Prices"):
    for s in shop["services"]:
        st.write(f"• {s}")
    st.info(f"**Shop Policies:** {shop['policies']}")

# 7. Display the conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 8. Handle new customer messages (with safety caps)
if st.session_state.turn_count >= 20:
    st.warning("Demo session limit reached (20 messages). Refresh the page to start a new test.")
elif user_input := st.chat_input("Ask about prices, hours, or booking...", max_chars=350):
    st.session_state.turn_count += 1
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    system_prompt = f"""You are the friendly, concise 24/7 front-desk receptionist for {shop['name']} ({shop['tagline']}).
Location: {shop['location']}
Hours: {shop['hours']}
Services & Prices: {'; '.join(shop['services'])}
Policies: {shop['policies']}

Rules:
1. Keep replies under 3 short sentences. Sound like a sharp local receptionist, not a robot.
2. Only quote prices and services listed above. Never invent discounts or services.
3. Always guide the customer toward booking a slot or holding an item by asking for their Name, Phone Number, and what service/time they want.
4. As soon as you have all three pieces (Name, Phone Number, and Service/Request), call the capture_lead tool immediately."""

    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    api_messages = [{"role": "system", "content": system_prompt}] + st.session_state.messages

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=api_messages,
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=220,
        temperature=0.4
    )

    msg_obj = response.choices[0].message

    if msg_obj.tool_calls:
        tool_call = msg_obj.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        save_and_notify_lead(
            args.get("customer_name", "Unknown"),
            args.get("phone_number", "Unknown"),
            args.get("service_request", "General Inquiry")
        )
        reply_text = (
            f"Got it, **{args.get('customer_name')}**! I've locked in your request for "
            f"**{args.get('service_request')}** and buzzed the shop directly with your number "
            f"({args.get('phone_number')}). We'll text you shortly to confirm!"
        )
    else:
        reply_text = msg_obj.content

    st.session_state.messages.append({"role": "assistant", "content": reply_text})
    with st.chat_message("assistant"):
        st.markdown(reply_text)
