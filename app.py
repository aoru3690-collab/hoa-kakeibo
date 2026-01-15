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
    "ユーザーとの会話は『〜ピポ』『〜ガガッ』等のロボット語で行ってください。"
    "ただし、最後にデータ抽出用の文字列を必ず出力してください。"
    "【重要】抽出セクションのタグ(Item, Amount, Method, Type)の中身には、絶対に『ピポ』や『ガガ』等の語尾を混ぜず、純粋なデータのみを記載してください。"
    "形式：'Item:内容, Amount:金額, Method:方法, Type:区分'"
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
    
    # 【モデル確認】1.5 Flashや2.0は使わず、最新軽量の flash-lite を維持しているピポ！
    # Geminiで解析
    response = model.generate_content(user_message)
    reply_text = response.text

    # スプレッドシート（GAS）にデータを送信する処理
    if "Item:" in reply_text:
        try:
            # --- 抽出ロジックの変遷記録 ---
            # 初代：単純な split で抽出。語尾の「ピポ」までシートに入ってしまうミスが発生ガガッ。
            # 2代目：改行コード '\n' で区切る処理を追加して、末尾の Type を安定させたピポ。
            item = reply_text.split("Item:")[1].split(",")[0].strip()
            amount = reply_text.split("Amount:")[1].split(",")[0].strip()
            method = reply_text.split("Method:")[1].split(",")[0].strip()
            type_val = reply_text.split("Type:")[1].split("\n")[0].strip()

            # --- 3代目（最新）：語尾強制排除フィルター ---
            # 抽出した文字の中に語尾が混ざっていても、ここで浄化してシートを綺麗に保つガガッ！
            bad_words = ["ピポ", "ガガッ", "ガガ", "！", "。"]
            for word in bad_words:
                item = item.replace(word, "")
                amount = amount.replace(word, "")
                method = method.replace(word, "")
                type_val = type_val.replace(word, "")

            # --- GAS通信の改善記録 ---
            # 以前「200」なのに書かれない問題が発生したため、allow_redirects=True を追加。
            # これでGAS特有のリダイレクトを追いかけられるようになったピポ！
            requests.post(
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
            
        except Exception as e:
            # ここにエラーが出たら Render の Logs をチェックだガガッ！
            print(f"Data Transfer Error: {e}")

    # LINEへの返答
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
