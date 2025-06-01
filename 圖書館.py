# -*- coding: utf-8 -*-
# 移除了 Colab 特有的 Notebook 描述信息

# Python 腳本不應包含 !pip 或 !apt-get 指令
# 這些安裝應該由 GitHub Actions workflow 處理

# print("--- OCR 套件檢查/安裝完畢 ---") # 這些 print 可以在腳本開始時保留一個總的
# print("--- ChromeDriver 設定檢查完畢 ---")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import os
import shutil
from datetime import datetime
import re 

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter
except ImportError:
    print("錯誤：Pytesseract 或 Pillow 未安裝。OCR 功能將不可用。")
    pytesseract = None

print("--- Python 腳本開始執行 ---")
print("--- 模組匯入完成 ---")

# --- 從環境變數讀取登入資訊 ---
LIBRARY_CARD_NUMBER = "A125239928"  # <--- 請替換成你的讀者證號
PASSWORD = "s2213511"              # <--- 請替換成你的密碼

if not LIBRARY_CARD_NUMBER or not PASSWORD:
    print("錯誤：環境變數 LIBRARY_CARD_NUMBER 或 PASSWORD 未設定！")
    exit(1) # 在排程中，如果缺少關鍵配置，應該退出
# --- 讀取環境變數結束 ---

LOGIN_PAGE_URL = "https://rwd-library.taichung.gov.tw/webpac_rwd/search.cfm"
CAPTCHA_IMAGE_FILENAME = "captcha_library.png"
PROCESSED_CAPTCHA_IMAGE_FILENAME = "captcha_library_processed.png"

driver = None
unique_user_data_dir = None

def solve_captcha_with_ocr(image_path):
    if pytesseract is None or not os.path.exists(image_path):
        print("OCR 功能不可用或圖片不存在。")
        return None
    try:
        img = Image.open(image_path)
        img_gray = img.convert('L')
        threshold = 135 
        img_binary = img_gray.point(lambda x: 0 if x < threshold else 255, '1')
        current_processed_img = img_binary
        current_processed_img.save(PROCESSED_CAPTCHA_IMAGE_FILENAME)
        custom_config = r'-l eng --oem 3 --psm 7 -c tessedit_char_whitelist=0123456789'
        text = pytesseract.image_to_string(current_processed_img, config=custom_config)
        recognized_text = ''.join(filter(str.isdigit, text)).strip()
        print(f"OCR 清理後結果 (純數字): '{recognized_text}'")
        if len(recognized_text) == 5:
            return recognized_text
        else:
            return None
    except Exception as e:
        print(f"OCR 識別過程中發生錯誤: {e}")
        return None

def solve_captcha_manually(image_path): # 在無人值守的排程中，這個函數可能不會被觸發或無效
    if os.path.exists(image_path):
        # 在 GitHub Actions 中無法進行交互式輸入，也無法直接顯示圖片
        print(f"OCR 識別失敗。圖片已保存為 {PROCESSED_CAPTCHA_IMAGE_FILENAME} (在 runner 環境中)。")
        print("在排程模式下，無法手動輸入驗證碼。如果 OCR 持續失敗，請檢查 OCR 邏輯或驗證碼圖片。")
        return None # 或者拋出異常
    else:
        print(f"錯誤：找不到驗證碼圖片 {image_path}")
        return None

def get_borrowed_books(driver, wait):
    borrowed_items_details = []
    try:
        print("\n--- 開始導航至已借書刊 ---")
        my_study_link_locator = (By.ID, "shelf_link")
        my_study_link = wait.until(EC.element_to_be_clickable(my_study_link_locator))
        my_study_link.click()
        print("已點擊「我的書房」。")
        time.sleep(3) 

        borrowing_record_expander_locator = (By.XPATH, "//ul[contains(@class, 'dot')]/li[normalize-space(text()[1])='借閱記錄']/a[@class='close']")
        try:
            expander_button = wait.until(EC.element_to_be_clickable(borrowing_record_expander_locator))
            expander_button.click()
        except TimeoutException:
            borrowing_record_section_li_locator_alt = (By.XPATH, "//ul[contains(@class, 'dot')]/li[normalize-space(text()[1])='借閱記錄']")
            borrowing_record_section_li = wait.until(EC.element_to_be_clickable(borrowing_record_section_li_locator_alt))
            borrowing_record_section_li.click()
        print("已點擊「借閱記錄」區域。")
        time.sleep(2) 

        borrowed_list_link_locator = (By.XPATH, "//div[contains(@class, 'slide-box')]//a[@href='shelf_borrow.cfm' and normalize-space(text())='已借書']")
        borrowed_list_link = wait.until(EC.element_to_be_clickable(borrowed_list_link_locator))
        borrowed_list_link.click()
        print("已點擊「已借書」。")
        time.sleep(3)

        book_box_locator = (By.CSS_SELECTOR, "div.book-list div.book-box")
        print("等待書籍列表載入...")
        wait.until(EC.presence_of_element_located(book_box_locator))
        
        book_boxes = driver.find_elements(*book_box_locator)
        
        if not book_boxes:
            print("在「已借書刊」頁面未找到任何書籍區塊。")
            no_books_message_locator = (By.XPATH, "//*[contains(text(),'目前無借閱資料') or contains(text(),'查無資料')]")
            try:
                no_books_msg = driver.find_element(*no_books_message_locator)
                if no_books_msg.is_displayed(): print(f"系統提示: {no_books_msg.text.strip()}")
            except: pass
            return []

        print(f"\n--- 已借書刊詳細資訊 (共 {len(book_boxes)} 本) ---")
        for i, box in enumerate(book_boxes):
            book_detail = {"書名": "N/A", "到期日": "N/A", "續借次數": "N/A", "預約人數": "N/A"}
            try:
                title_element = box.find_element(By.CSS_SELECTOR, "a.bookname.text-h3")
                book_detail["書名"] = title_element.get_attribute("title").strip()

                info_elements = box.find_elements(By.CSS_SELECTOR, "div.two-item.book-item p.info_long")
                for info_p in info_elements:
                    text = info_p.text.strip()
                    if "到期日：" in text:
                        book_detail["到期日"] = text.replace("到期日：", "").strip()
                    elif "續借次數：" in text:
                        match = re.search(r'\d+', text.replace("續借次數：", "").strip())
                        if match: book_detail["續借次數"] = match.group(0)
                    elif "預約人數：" in text:
                        match = re.search(r'\d+', text.replace("預約人數：", "").strip())
                        if match: book_detail["預約人數"] = match.group(0)
                
                borrowed_items_details.append(book_detail)
            except Exception as e:
                print(f"抓取第 {i+1} 本書詳細資訊時出錯: {e}")
        
        if not borrowed_items_details:
             print("未能成功提取任何書籍的詳細資訊。")
    except TimeoutException as te:
        print(f"導航或抓取已借書刊時發生超時: {te}")
        # ... (錯誤處理與之前相同) ...
    except NoSuchElementException as nse:
        print(f"導航或抓取已借書刊時元素未找到: {nse}")
        # ... (錯誤處理與之前相同) ...
    except Exception as e:
        print(f"導航或抓取已借書刊時發生未知錯誤: {e}")
        # ... (錯誤處理與之前相同) ...
    return borrowed_items_details

try:
    print("--- 開始設定 Chrome 選項 ---")
    chrome_options = Options()
    
    # ---- 修改：明確指定 Chromium 二進制檔案路徑 ----
    chrome_options.binary_location = "/usr/bin/chromium-browser" 
    # ---------------------------------------------
    
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920x1080')
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36" # 保持一個常見的 User Agent
    chrome_options.add_argument(f'user-agent={user_agent}')
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    unique_user_data_dir = f"/tmp/chrome_user_data_library_{timestamp}" # 在無頭環境中，這個可能不是必需的，但保留無害
    os.makedirs(unique_user_data_dir, exist_ok=True)
    chrome_options.add_argument(f'--user-data-dir={unique_user_data_dir}')
    print(f"已設定 User-Agent, User Data Directory: {unique_user_data_dir}, Binary Location: {chrome_options.binary_location}")
    print("--- Chrome 選項設定完成 ---")

    print("--- 開始設定 ChromeDriver Service ---")
    # Selenium 4 的 Service() 通常能自動找到由 apt-get 安裝的 chromedriver
    # 如果你的 .yml 檔案中加入了 ln -s ... 命令將 chromedriver 連結到 /usr/local/bin/chromedriver，
    # 或者 chromedriver 包將其安裝到了 /usr/bin/chromedriver，那麼 Service() 應該能找到。
    service = Service() 
    # 如果仍然報錯找不到 chromedriver，則需要在 .yml 中確保 chromedriver 在 PATH 中，
    # 或者在這裡明確指定路徑：
    # chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver") # 從環境變數讀取或使用預設
    # print(f"使用 ChromeDriver 路徑: {chromedriver_path}")
    # service = Service(executable_path=chromedriver_path)
    print("--- ChromeDriver Service 設定完成 ---")

    print("--- 開始初始化 WebDriver ---")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    wait = WebDriverWait(driver, 20) 
    print("--- WebDriver 成功啟動！ ---")

    driver.get(LOGIN_PAGE_URL)
    time.sleep(5); print("已等待 5 秒讓頁面初步載入。")

    js_to_execute = "login_checker_kit_check('close_fancybox','');"
    driver.execute_script(js_to_execute)
    print(f"已執行 JavaScript: {js_to_execute}")
    time.sleep(7); print("已等待 7 秒讓登入框 JS 及動畫執行。")

    lobibox_window_locator = (By.XPATH, "//div[contains(@class, 'lobibox-window') and .//span[@class='lobibox-title' and normalize-space(text())='登入']]")
    lobibox_window = wait.until(EC.visibility_of_element_located(lobibox_window_locator))
    print("Lobibox 登入彈出框已出現！")

    card_no_input = wait.until(EC.element_to_be_clickable((By.ID, "hidid")))
    password_input = lobibox_window.find_element(By.ID, "password")
    captcha_image_element = lobibox_window.find_element(By.CSS_SELECTOR, "#captcha_span img.verification-code")
    captcha_input_field = lobibox_window.find_element(By.ID, "validateCode")
    submit_button_modal = lobibox_window.find_element(By.XPATH, ".//input[@value='登入' and @onclick='submitForm();']")


    card_no_input.send_keys(LIBRARY_CARD_NUMBER)
    password_input.send_keys(PASSWORD)
    print("已填寫帳號密碼。")

    captcha_image_element.screenshot(CAPTCHA_IMAGE_FILENAME)
    captcha_solution = solve_captcha_with_ocr(CAPTCHA_IMAGE_FILENAME) 
    if not captcha_solution: 
        # 在排程中，如果 OCR 失敗，我們不能依賴手動輸入
        print("OCR 識別失敗，且無法手動輸入。登入中止。")
        captcha_solution = None # 確保 captcha_solution 為 None 以跳過後續登入嘗試
        # 或者可以選擇 raise Exception("OCR 識別失敗") 來使 workflow 明確失敗

    if captcha_solution:
        captcha_input_field.send_keys(captcha_solution)
        print(f"已輸入驗證碼: {captcha_solution}")
        
        driver.execute_script("arguments[0].click();", submit_button_modal)
        print("已點擊彈出框內的登入按鈕。")
        time.sleep(5) 

        login_successful = False
        try:
            WebDriverWait(driver, 7).until_not(EC.visibility_of_element_located(lobibox_window_locator))
            print("登入成功！ (Lobibox 登入框已消失)")
            login_successful = True
        except TimeoutException:
            print("登入失敗或仍在登入頁面 (Lobibox 登入框未消失)。可能是驗證碼錯誤、帳密錯誤或需要更長的等待時間。")
            # ... (錯誤訊息獲取邏輯與之前相同)
            try:
                error_msg_account = lobibox_window.find_element(By.ID, "idMsg")
                error_msg_pwd = lobibox_window.find_element(By.ID, "pwdMsg")
                error_msg_all = lobibox_window.find_element(By.ID, "AllMsg")
                full_error_message = ""
                if error_msg_account.is_displayed() and error_msg_account.text.strip(): full_error_message += f"帳號錯誤: {error_msg_account.text.strip()} "
                if error_msg_pwd.is_displayed() and error_msg_pwd.text.strip(): full_error_message += f"密碼錯誤: {error_msg_pwd.text.strip()} "
                if error_msg_all.is_displayed() and error_msg_all.text.strip(): full_error_message += f"總體錯誤: {error_msg_all.text.strip()} "
                if full_error_message: print(f"系統提示訊息: {full_error_message}")
                else: print("未找到明確錯誤訊息，但登入框仍在。")
            except NoSuchElementException: print("未找到預期錯誤訊息元素。")
            if driver: driver.save_screenshot("login_failed_screenshot.png")


        if login_successful:
            borrowed_books_details_list = get_borrowed_books(driver, wait)
            if borrowed_books_details_list:
                print("\n--- 最終獲取的已借書刊詳細資訊 ---")
                for item in borrowed_books_details_list:
                    print(f"書名: {item['書名']}")
                    print(f"  到期日: {item['到期日']}")
                    print(f"  續借次數: {item['續借次數']}")
                    print(f"  預約人數: {item['預約人數']}")
                    print("-" * 30)
            else:
                print("\n未能獲取已借書刊列表。")
    else:
        print("未能獲取驗證碼 (OCR失敗且無法手動輸入)，登入中止。")

except ValueError as ve: 
    print(f"設定錯誤: {ve}")
    # 对于排程，可能也需要退出
    # exit(1)
except TimeoutException as te:
    print(f"操作超時: {te}")
    if driver: 
        try:
            driver.save_screenshot("timeout_error_page.png")
            with open("timeout_error_page.html", "w", encoding="utf-8") as f: f.write(driver.page_source)
            print("已保存超時時的頁面截圖和源碼。")
        except: pass
except NoSuchElementException as nse:
    print(f"元素未找到: {nse}")
    if driver: 
        try:
            driver.save_screenshot("element_not_found_error.png")
            with open("element_not_found_page.html", "w", encoding="utf-8") as f: f.write(driver.page_source)
            print("已保存元素未找到時的頁面源碼。")
        except: pass
except Exception as e:
    print(f"發生未預期錯誤: {e}")
    if driver: 
        try:
            driver.save_screenshot("unexpected_error.png")
            with open("unexpected_error_page.html", "w", encoding="utf-8") as f: f.write(driver.page_source)
            print("未預期錯誤截圖和源碼已保存。")
        except: pass
finally:
    if driver: 
        driver.quit()
        print("--- WebDriver 已關閉 ---")
    if unique_user_data_dir and os.path.exists(unique_user_data_dir):
        try: 
            shutil.rmtree(unique_user_data_dir)
            print(f"已清理 User Data Directory: {unique_user_data_dir}")
        except Exception as e: 
            print(f"清理 User Data Directory 時出錯 ({unique_user_data_dir}): {e}")
    print("--- Python 腳本執行完畢 ---")
