# Deploy the Satellite Tracking Dashboard

## Run locally first

From this project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Open the local URL shown in the terminal, normally `http://localhost:8501`.

## Deploy online with Streamlit Community Cloud

1. Create a GitHub repository, for example `autonomous-satellite-tracking-ground-station`.
2. Upload these files to the repository root:
   - `streamlit_app.py`
   - `tracker.py`
   - `simulate_rotator.py`
   - `requirements.txt`
   - `README.md` or `PROTOTYPE_README.md`
3. Do not upload `.venv`, `data`, or generated `output` files.
4. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) with GitHub.
5. Select **Create app**, choose the repository and branch, and set the entrypoint to `streamlit_app.py`.
6. Choose an app URL and select **Deploy**.
7. Test the published URL by selecting **Predict next pass**.

The dashboard needs internet access when the **Download fresh orbital data** option is selected.

