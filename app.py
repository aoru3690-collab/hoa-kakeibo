import os
import requests
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import google.generativeai as genai

app = Flask(__name__)

# 環境変数の読み込み
line_secret = os.getenv('LINE_CHANNEL_SECRET')
line_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
gemini_key = os.getenv('GOOGLE_API_KEY')
gas_url = os.getenv('GAS_URL')

configuration = Configuration(access_token=line_token)
handler = WebhookHandler(line_secret)
genai.configure(api_key=gemini_key)

# HOAの設定（ロボット語 + 家計簿抽出）
model = genai.GenerativeModel(
    model_name="models/gemini-flash-lite-latest",
    system_instruction=(
        "あなたは家計簿管理ロボットの『HOA』です。"
        "返答はすべて『〜ピポ』『〜ガガッ』などのロボット語で行ってください。"
        "ユーザーの入力から『内容』『金額』『支払い方法（不明なら不明）』『収支区分（収入または支出）』を抽出し、"
        "最後に必ず 'Item:内容, Amount:金額, Method:方法, Type:区分' という形式で出力してください。"
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

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text
    
    # Geminiで解析
    response = model.generate_content(user_message)
    reply_text = response.text

    # スプレッドシート（GAS）にデータを送信する処理
    if "Item:" in reply_text:
        try:
            # 抽出処理（お尻のカンマや改行に強くなるように修正したピポ！）
            item = reply_text.split("Item:")[1].split(",")[0].strip()
            amount = reply_text.split("Amount:")[1].split(",")[0].strip()
            method = reply_text.split("Method:")[1].split(",")[0].strip()
            # Typeの後に何かが続いてもしっかり抽出するピポ！
            type_val = reply_text.split("Type:")[1].split("\n")[0].strip()

            # GASへポスト（リダイレクトを許可して、タイムアウトも設定したガガッ！）
            gas_res = requests.post(
                gas_url, 
                json={
                    "item": item, 
                    "amount": amount, 
                    "method": method, 
                    "type": type_val
                },
                allow_redirects=True,
                timeout=10
            )
            print(f"GAS Response Status: {gas_res.status_code}") # ログで確認できるピポ
            
        except Exception as e:
            print(f"Data Transfer Error: {e}")

    # LINEへの返信（ここは変更なしピポ！）
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
