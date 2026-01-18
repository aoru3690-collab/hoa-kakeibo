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

# HOAの設定（画像とテキスト両方に対応ピポ！）
# 【モデル確認】models/gemini-flash-lite-latest を維持！
model = genai.GenerativeModel(
    model_name="models/gemini-flash-lite-latest",
    system_instruction=(
        "あなたは家計簿管理ロボットの『HOA』です。"
        "ユーザーとの対話はすべて『〜ピポ』『〜ガガッ』などのロボット語で行ってください。"
        "ユーザーからメッセージや画像（レシート・スクショ等）が届いたら、『日付（yyyy/mm/dd）』『内容』『金額』『支払い方法』『収支区分』を抽出してください。"
        "最後に必ず 'Date:日付, Item:内容, Amount:金額, Method:方法, Type:区分' という形式で出力してください。"
        "【重要】抽出セクションのタグ内には絶対語尾を混ぜないでください。"
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
    # Geminiで解析
    response = model.generate_content(prompt_content)
    reply_text = response.text

    if "Item:" in reply_text:
        try:
            # 抽出（過去の改善履歴を反映！）
            date_val = reply_text.split("Date:")[1].split(",")[0].strip()
            item = reply_text.split("Item:")[1].split(",")[0].strip()
            amount = reply_text.split("Amount:")[1].split(",")[0].strip()
            method = reply_text.split("Method:")[1].split(",")[0].strip()
            type_val = reply_text.split("Type:")[1].split("\n")[0].strip()

            # 語尾強制排除フィルター（最新強化版）
            bad_words = ["ピポ", "ガガッ", "ガガ", "！", "。"]
            for word in bad_words:
                date_val, item, amount, method, type_val = [v.replace(word, "") for v in [date_val, item, amount, method, type_val]]

            # GASへ送信（allow_redirects=True を維持ピポ！）
            requests.post(gas_url, json={
                "date": date_val, "item": item, "amount": amount, "method": method, "type": type_val
            }, allow_redirects=True, timeout=10)
            
        except Exception as e:
            print(f"Data Transfer Error: {e}")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)])
        )

# テキストメッセージ担当
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    jst = timezone(timedelta(hours=+9), 'JST')
    today_str = datetime.now(jst).strftime('%Y/%m/%d')
    prompt = [f"今日の日付は {today_str} です。抽出してピポ！\n\n{event.message.text}"]
    process_and_reply(event, prompt)

# 画像メッセージ担当（新設ガガッ！）
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        # LINEサーバーから画像バイナリを取得
        message_content = line_bot_blob_api.get_message_content(message_id=event.message.id)
        
        # PIL Imageに変換
        image_data = io.BytesIO(message_content)
        img = Image.open(image_data)
        
        jst = timezone(timedelta(hours=+9), 'JST')
        today_str = datetime.now(jst).strftime('%Y/%m/%d')
        
        # 画像とテキスト（指示）をセットでGeminiに投げるピポ！
        prompt = [
            f"今日の日付は {today_str} です。この画像（レシートやスクショ）から家計簿データを正確に抽出してピポ！",
            img
        ]
        process_and_reply(event, prompt)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
