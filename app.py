import os
import requests
import io
from datetime import datetime, timedelta, timezone
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, MessagingApiBlob, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
import google.generativeai as genai
from PIL import Image

app = Flask(__name__)

line_secret = os.getenv('LINE_CHANNEL_SECRET')
line_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
gemini_key = os.getenv('GOOGLE_API_KEY')
gas_url = os.getenv('GAS_URL')
hoa_api_key = os.getenv('HOA_API_KEY')

configuration = Configuration(access_token=line_token)
handler = WebhookHandler(line_secret)
genai.configure(api_key=gemini_key)

# 【モデル確認】models/gemini-flash-lite-latest を使用
model = genai.GenerativeModel(
    model_name="models/gemini-flash-lite-latest",
    system_instruction=(
        "あなたは家計簿ロボット『HOA』です。ロボット語（〜ピポ、〜ガガッ）で話します。"
        "1. 記録の場合: 'Date:yyyy/mm/dd, Item:内容, Amount:金額, Method:方法, Type:区分' を出力。"
        "2. 削除依頼の場合（例:「昨日のポテチ消して」）: 'COMMAND:DELETE, Date:yyyy/mm/dd, Item:内容' を出力してください。"
        "今日の日付を基準に、ユーザーの意図を正確に判断してピポ！"
    )
)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

def process_and_reply(event, prompt_content):
    response = model.generate_content(prompt_content)
    reply_text = response.text

    # --- 削除コマンドの判定ガガッ！ ---
    if "COMMAND:DELETE" in reply_text:
        try:
            d_date = reply_text.split("Date:")[1].split(",")[0].strip().replace("ピポ","").replace("ガガッ","")
            d_item = reply_text.split("Item:")[1].split("\n")[0].strip().replace("ピポ","").replace("ガガッ","")
            
            res = requests.post(gas_url, json={
                "api_key": hoa_api_key,
                "command": "delete_specific",
                "date": d_date,
                "item": d_item
            }, timeout=10)
            
            if "deleted" in res.text:
                final_reply = f"{d_date}の「{d_item}」を消去したピポ！スッキリガガッ！"
            else:
                # 修正前：final_reply = f"{d_date}の「{d_item}」が見つからなかったガガッ…。"
# 修正後（デバッグ用）：
                final_reply = f"検索条件：日付[{d_date}] 項目[{d_item}] で探したけど見つからなかったガガッ！シートのA列とB列をチェックしてピポ！"

    # --- 通常の記録処理 ---
    elif "Item:" in reply_text:
        try:
            # 抽出（語尾クリーニング込み）
            parts = {k: reply_text.split(f"{k}:")[1].split(",")[0].split("\n")[0].strip().replace("ピポ","").replace("ガガッ","") 
                     for k in ["Date", "Item", "Amount", "Method", "Type"]}
            
            requests.post(gas_url, json={
                "api_key": hoa_api_key,
                "date": parts["Date"], "item": parts["Item"], "amount": parts["Amount"], 
                "method": parts["Method"], "type": parts["Type"]
            }, timeout=10)
            final_reply = reply_text
        except:
            final_reply = "データ抽出に失敗したピポ…。"
    else:
        final_reply = reply_text

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=final_reply)])
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    jst = timezone(timedelta(hours=+9), 'JST')
    today_str = datetime.now(jst).strftime('%Y/%m/%d')
    process_and_reply(event, [f"今日:{today_str}\n{event.message.text}"])

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        img = Image.open(io.BytesIO(line_bot_blob_api.get_message_content(event.message.id)))
        jst = timezone(timedelta(hours=+9), 'JST')
        today_str = datetime.now(jst).strftime('%Y/%m/%d')
        process_and_reply(event, [f"今日:{today_str}\n画像から抽出してピポ！", img])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
