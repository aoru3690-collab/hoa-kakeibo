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

# 環境変数の読み込み
line_secret = os.getenv('LINE_CHANNEL_SECRET')
line_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
gemini_key = os.getenv('GOOGLE_API_KEY')
gas_url = os.getenv('GAS_URL')
hoa_api_key = os.getenv('HOA_API_KEY')

configuration = Configuration(access_token=line_token)
handler = WebhookHandler(line_secret)
genai.configure(api_key=gemini_key)

# HOAの設定（ロボット語を卒業）
# 【モデル確認】models/gemini-flash-lite-latest を使用
model = genai.GenerativeModel(
    model_name="models/gemini-flash-lite-latest",
    system_instruction=(
        "あなたは家計簿管理アシスタントの『HOA』です。丁寧な日本語で対応してください。"
        "1. 記録の場合: 'Date:yyyy/mm/dd, Item:内容, Amount:金額, Method:方法, Type:区分' を出力。"
        "2. 削除依頼の場合: 'COMMAND:DELETE, Date:yyyy/mm/dd, Item:内容' を出力。"
        "抽出タグ内には、余計な記号（！や。）や挨拶を絶対に混ぜないでください。"
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

def clean_value(val):
    """不要な記号や空白、旧ロボット語を徹底除去する関数"""
    bad_chars = ["ピポ", "ガガッ", "！", "!", "。", ".", " ", "　"]
    for char in bad_chars:
        val = val.replace(char, "")
    return val.strip()

def process_and_reply(event, prompt_content):
    response = model.generate_content(prompt_content)
    reply_text = response.text
    final_reply = ""

    # --- 1. 削除コマンドの判定 ---
    if "COMMAND:DELETE" in reply_text:
        try:
            # データの抽出と徹底クリーニング
            d_date = clean_value(reply_text.split("Date:")[1].split(",")[0])
            d_item = clean_value(reply_text.split("Item:")[1].split("\n")[0])
            
            res = requests.post(gas_url, json={
                "api_key": hoa_api_key,
                "command": "delete_specific",
                "date": d_date,
                "item": d_item
            }, timeout=10)
            
            if "deleted" in res.text:
                final_reply = f"{d_date}の「{d_item}」を削除しました。スッキリしましたね！"
            else:
                final_reply = f"検索条件:[{d_date}][{d_item}]で見つかりませんでした。シートの記載を確認してください。"
        except Exception as e:
            print(f"Delete Logic Error: {e}")
            final_reply = "削除処理中にエラーが発生しました。"

    # --- 2. 通常の記録処理 ---
    elif "Item:" in reply_text:
        try:
            parts = {}
            for k in ["Date", "Item", "Amount", "Method", "Type"]:
                raw_val = reply_text.split(f"{k}:")[1].split(",")[0].split("\n")[0]
                parts[k] = clean_value(raw_val)
            
            requests.post(gas_url, json={
                "api_key": hoa_api_key,
                "date": parts["Date"], 
                "item": parts["Item"], 
                "amount": parts["Amount"], 
                "method": parts["Method"], 
                "type": parts["Type"]
            }, timeout=10)
            final_reply = reply_text
        except Exception as e:
            print(f"Record Logic Error: {e}")
            final_reply = "データの抽出中にエラーが発生しました。"

    # --- 3. その他 ---
    else:
        final_reply = reply_text

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=final_reply)]
            )
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    jst = timezone(timedelta(hours=+9), 'JST')
    today_str = datetime.now(jst).strftime('%Y/%m/%d')
    # 指示文からもロボット語を除去
    process_and_reply(event, [f"今日の日付は {today_str} です。以下の内容を解析してください。\n\n{event.message.text}"])

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        img = Image.open(io.BytesIO(line_bot_blob_api.get_message_content(event.message.id)))
        jst = timezone(timedelta(hours=+9), 'JST')
        today_str = datetime.now(jst).strftime('%Y/%m/%d')
        process_and_reply(event, [f"今日の日付は {today_str} です。画像から家計簿データを抽出してください。", img])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
