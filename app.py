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

configuration = Configuration(access_token=line_token)
handler = WebhookHandler(line_secret)
genai.configure(api_key=gemini_key)

# HOAの設定
# 【モデル確認】models/gemini-flash-lite-latest を使用
model = genai.GenerativeModel(
    model_name="models/gemini-flash-lite-latest",
    system_instruction=(
        "あなたは家計簿管理ロボットの『HOA』です。"
        "ユーザーとの対話はすべて『〜ピポ』『〜ガガッ』などのロボット語で行ってください。"
        "ユーザーの入力から『日付（yyyy/mm/dd）』『内容』『金額』『支払い方法』『収支区分』を抽出してください。"
        "最後に必ず 'Date:日付, Item:内容, Amount:金額, Method:方法, Type:区分' という形式で出力してください。"
        "抽出タグ内には語尾を混ぜないでください。"
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

# --- 共通のデータ送信・返信ロジック ---
def process_and_reply(event, prompt_content):
    response = model.generate_content(prompt_content)
    reply_text = response.text

    if "Item:" in reply_text:
        try:
            date_val = reply_text.split("Date:")[1].split(",")[0].strip()
            item = reply_text.split("Item:")[1].split(",")[0].strip()
            amount = reply_text.split("Amount:")[1].split(",")[0].strip()
            method = reply_text.split("Method:")[1].split(",")[0].strip()
            type_val = reply_text.split("Type:")[1].split("\n")[0].strip()

            # 語尾強制排除フィルター
            bad_words = ["ピポ", "ガガッ", "ガガ", "！", "。"]
            for word in bad_words:
                date_val, item, amount, method, type_val = [v.replace(word, "") for v in [date_val, item, amount, method, type_val]]

            # GASへ送信
            res = requests.post(gas_url, json={
                "date": date_val, "item": item, "amount": amount, "method": method, "type": type_val
            }, allow_redirects=True, timeout=10)
            
            # 【秘匿性UP】データの中身（itemやamount）は print しないピポ！
            # 成功したかどうかという「ステータス」だけをログに残すガガッ。
            print(f"INFO: Data Transfer to GAS Status: {res.status_code}")
            
        except Exception as e:
            # エラー時も詳細は出さず、発生したことだけを記録するピポ
            print("ERROR: Data extraction or transfer failed.")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)])
        )

# テキストメッセージ担当
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # ユーザーの入力内容をログに出さないように print を削除したガガッ！
    jst = timezone(timedelta(hours=+9), 'JST')
    today_str = datetime.now(jst).strftime('%Y/%m/%d')
    prompt = [f"今日の日付は {today_str} です。抽出してピポ！\n\n{event.message.text}"]
    process_and_reply(event, prompt)

# 画像メッセージ担当
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        message_content = line_bot_blob_api.get_message_content(message_id=event.message.id)
        
        image_data = io.BytesIO(message_content)
        img = Image.open(image_data)
        
        jst = timezone(timedelta(hours=+9), 'JST')
        today_str = datetime.now(jst).strftime('%Y/%m/%d')
        
        prompt = [
            f"今日の日付は {today_str} です。この画像から家計簿データを抽出してピポ！",
            img
        ]
        process_and_reply(event, prompt)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
