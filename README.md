# BOOX 每日看板

給 **BOOX Go 10.3**（Android 12、2480×1860、灰階電子紙）用的直向看板。每天台北時間 **06:00** 與 **18:00** 重新整理新竹天氣、未來七天行程、以及台美股收盤，排成黑白高對比的 1860×2480 畫面，放到 GitHub Pages。閱讀器上的 App 約在 **06:05** 與 **18:05** 各重新載入一次。

畫面文字皆為繁體中文。漲跌用「＋／－」與「▲／▼」標示，不靠顏色。

公開網址：<https://bradylife-svg.github.io/boox-dashboard/>（`index.html` 與 `dashboard.png`）。

## 怎麼運作

```
Open-Meteo、證交所、CNBC（Yahoo 備援）、私人 Google 日曆 iCal
        │
        ▼
GitHub Actions（UTC 22:00 與 10:00，即台北 06:00 與 18:00）
產生 site/index.html、site/dashboard.png
        │
        ▼
GitHub Pages
        │
        ▼
BOOX App：06:05、18:05 與手動點擊時重新載入
```

免費的 GitHub 代管執行器有時會晚幾分鐘才開始，所以裝置端刻意晚五分鐘再刷新，避免抓到舊的一版。

產生出來的 HTML／PNG **不會**提交進 Git。頁面若含行程，只存在 Pages 上。

## 畫面上有什麼

1. **表頭**：日期、星期、更新時間，地點為新竹。
2. **天氣**：今日氣溫區間、降雨機率、目前氣溫與濕度；06:00–23:00 的氣溫折線與降雨機率長條，下方數字列會把「目前這一小時」反白；右側兩格是接下來兩天的預報。
3. **本週行程**：台北時間今天起連續七天，依日分組。沒有行程的日子顯示「—」。全天行程標「全天」，重複行程會展開成各別的一次。
4. **股市**：一格一檔，依序是加權指數、道瓊、標普 500、那斯達克、0050、2330、00400A。顯示最近一次已公布的收盤、漲跌與漲跌幅。早上六點時台股當天還沒開盤，美股則是上一個交易時段的收盤。

某一來源失敗時，該格寫「資料暫缺」，不會補假數字。若還沒設定日曆密鑰，行程區會寫 **尚未設定日曆**，其餘區塊照常產生，工作流程不會因此失敗。

## 資料來源

| 區塊 | 來源 |
| --- | --- |
| 天氣 | [Open-Meteo](https://open-meteo.com/) 預報（新竹市區座標，免金鑰） |
| 行程 | 你自己的 Google 日曆秘密 iCal 網址，經 `GCAL_ICS_URLS` 讀取 |
| 台股 | [臺灣證券交易所](https://www.twse.com.tw/)：`MI_INDEX`（加權指數）、OpenAPI `STOCK_DAY_ALL`（0050、2330、00400A） |
| 美股指數 | [CNBC Quotes](https://www.cnbc.com/)（`.DJI`、`.SPX`、`.IXIC`）；失敗時改試 Yahoo Finance |

## 設定 Google 日曆

秘密網址等於一把能讀整本日曆的鑰匙。只放在 GitHub Actions 密鑰裡，不要寫進程式、不要貼到議題或提交記錄，也不要寫進日誌。

1. 用電腦打開 [Google 日曆](https://calendar.google.com/)。
2. 左側「我的日曆」找到要顯示的那一本，點名稱右邊的直排三點，選 **設定和共用**。
3. 向下捲到 **整合日曆**。
4. 複製 **日曆的秘密地址（iCal 格式）**。網址通常以 `https://calendar.google.com/calendar/ical/` 開頭、以 `/basic.ics` 結尾。不要複製旁邊的「公開位址」。
5. 有多本日曆就各複製一次（例如個人、家務、課表）。不想公開的日曆就不要加。

### 加到儲存庫密鑰

1. 打開這個儲存庫的 **Settings → Secrets and variables → Actions**。
2. **New repository secret**。
3. Name 填 `GCAL_ICS_URLS`（大小寫要完全一樣）。
4. Secret 裡每行放一個網址。也可以用逗號分隔。
5. 儲存。

工作流程只會把網址拿去下載，不會印出網址，也不會把行程標題寫進 Actions 日誌。頁面本身會顯示行程標題，見下方「隱私」。

改完密鑰後，到 **Actions → 發佈晨間看板 → Run workflow** 手動跑一次，不用等到下一個 06:00 或 18:00。

## 啟用 GitHub Pages

工作流程會嘗試把 Pages 設成由 Actions 部署。權限常常不夠，**仍需要你手動確認一次**：

1. 儲存庫 **Settings → Pages**。
2. **Build and deployment** 的 **Source** 選 **GitHub Actions**（不是 Deploy from a branch）。
3. 若選單是空的，先到 **Actions** 分頁允許工作流程，再回到 Pages。
4. 到 **Actions → 發佈晨間看板**，按 **Run workflow**。
5. 綠燈之後，看板在 <https://bradylife-svg.github.io/boox-dashboard/>，圖片在 <https://bradylife-svg.github.io/boox-dashboard/dashboard.png>。

排程是 UTC `0 22 * * *`（台北 06:00）與 `0 10 * * *`（台北 18:00），另外可以隨時手動執行。新儲存庫的排程有時要等第一次手動執行之後才會穩定觸發。

### 隱私

這個儲存庫是公開的，GitHub Pages 也是公開的。設定日曆之後，**未來七天的行程標題會出現在上述網址**，任何人都能看到。只加入你願意公開的日曆；或是把儲存庫改成私人，並依 GitHub 方案決定 Pages 是否仍公開。

## 在 BOOX 上安裝 App

App 在 `android/`。`minSdk` 30、`targetSdk` 34，全螢幕、沒有動畫。預設用 WebView 開 Pages 網址；在畫面上 **長按** 可改成顯示 `dashboard.png`，再長按切回來。**點一下** 立即重新載入。

它用 `AlarmManager` 的精確鬧鐘，在裝置本地時間約 **06:05** 與 **18:05** 各響一次（請把 BOOX 時區設成台北）。響了會重新排下一次，所以兩個時間都會留著。重新開機或 App 更新後，`BOOT_COMPLETED` 會把兩個鬧鐘都再排一次。

### 下載 APK

合併到 `main` 之後（或在 Actions 手動執行 **建置 Android APK**），可以從兩處下載除錯版 `app-debug.apk`：

- Release：<https://github.com/bradylife-svg/boox-dashboard/releases/tag/boox-apk>
- 該次工作流程的 **Artifacts**（名稱 `boox-dashboard-debug-apk`）

### 安裝

1. 在 BOOX 的瀏覽器直接下載，或用 USB 把 `app-debug.apk` 拷到裝置。
2. 用檔案管理點開 APK。若系統擋住，到設定裡允許該來源「安裝未知的應用程式」。
3. 安裝後打開一次 **晨間看板**。這次開啟會排好兩個鬧鐘。
4. 若系統詢問精確鬧鐘（鬧鐘與提醒），請允許。沒有這項權限時，App 會改用較不準的鬧鐘，06:05／18:05 可能被系統延後。
5. 若 App 仍顯示「已停止運作」，請再打開一次。第二次會在畫面上顯示上次的錯誤堆疊（同時寫在應用程式資料夾的 `last-crash.txt`），把那個畫面拍下來即可，不必接 adb。看完後按「清除記錄並重試」。

## BOOX 使用提醒

電子紙不適合頻繁刷新。這個 App 一天只自動更新兩次。

- **不要凍結這個 App**。到 BOOX 的應用程式管理、閒置或「應用程式凍結」，把「晨間看板」排除。被凍結之後，開機與鬧鐘都不會跑，早上看到的會是昨天的畫面。
- **電池最佳化請放行**。Android 設定 → 應用程式 → 晨間看板 → 電池 → 選「不受限制」。不要把它留在省電限制清單裡。
- **電子紙刷新模式**用「正常」或全刷。控制中心的重新整理不要選極速、A2 或快速模式，那些模式殘影很重，細字和折線會糊掉。若 BOOX 能針對單一 App 指定刷新模式，請設成正常或全刷。
- **殘影**用控制中心的 **全刷** 清一次。每天更新後若還看得到上一幀，全刷即可，不必重新安裝。
- **網路**：06:00 與 18:00 前後請保持 Wi-Fi。沒有網路時，點一下畫面可再試。
- **方向**：頁面是直向 1860×2480。App 已鎖定直向，並關掉系統列。請把裝置直著放。
- **時區**設為 `Asia/Taipei`，06:05 與 18:05 才會對到台北時間。

## 在自己的電腦上產生

需要 Python 3.10 以上、Google Chrome 或 Chromium，以及繁體中文字型（Debian／Ubuntu：`fonts-noto-cjk`，字型家族名稱 `Noto Sans CJK TC`）。

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 generate_dashboard.py
```

產出在 `site/index.html` 與 `site/dashboard.png`（已列入 `.gitignore`）。沒有設定 `GCAL_ICS_URLS` 時，行程區是「尚未設定日曆」。

本機要帶日曆時，只放在環境變數，不要寫進檔案：

```bash
GCAL_ICS_URLS="$(cat ~/.config/boox-ics-urls)" python3 generate_dashboard.py
```

多個網址用換行或逗號分隔，跟 GitHub 密鑰的格式相同。

## 專案檔案

```
generate_dashboard.py          抓資料、產生 HTML 與 PNG
requirements.txt
tests/                         日曆展開與「尚未設定日曆」（不連私人網址）
.github/workflows/pages.yml    每天兩次發佈到 GitHub Pages
.github/workflows/android.yml  建置除錯版 APK，並在 main 發佈 Release
android/                       BOOX 全螢幕 App
```

## 你還需要在 GitHub 上做的事

程式合併之後，這三件無法完全靠工作流程代勞：

1. **Settings → Secrets and variables → Actions**，新增密鑰 `GCAL_ICS_URLS`。
2. **Settings → Pages → Source** 確認是 **GitHub Actions**。
3. 到 **Actions** 手動執行一次「發佈晨間看板」。若要立刻拿到 APK，再執行一次「建置 Android APK」（推上 `main` 且改動到 `android/` 時也會自己跑）。
