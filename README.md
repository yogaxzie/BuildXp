# buildXp 🚀

Platform build website instan dengan HTML/CSS/JS. Deploy dalam hitungan detik!

## Fitur
- ✅ Deploy HTML instan
- ✅ Free trial 7 hari
- ✅ VIP Membership
- ✅ Admin Panel
- ✅ Notifikasi real-time

## Admin Credentials
- Username: `Zbuild`
- Password: `252532`

## Deploy ke Render

1. Fork/push repo ini ke GitHub
2. Login ke [render.com](https://render.com)
3. Click "New Web Service"
4. Connect GitHub repo
5. Setting:
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT`
6. Click "Create Web Service"

## Local Development

```bash
pip install -r requirements.txt
python app.py
