import httpx

def test_full_http_auth_flow():
    base_url = "http://localhost:8000/api/v1/auth"
    admin_email = "newadmin@corp.com"
    password = "SecurePassword123!"

    print("\n[STEP 1] Registering Admin...")
    payload = {
        "email": admin_email,
        "password": password,
        "full_name": "New Workspace Admin",
        "company_name": "Acme Global Tech"
    }
    res = httpx.post(f"{base_url}/register/admin", json=payload, timeout=10.0)
    print(f"Register Status Code: {res.status_code}")
    print(f"Register Response: {res.json()}")
    assert res.status_code == 201, "Registration must return 201 Created"

    print("\n[STEP 2] Attempting Login Before Verification...")
    login_res = httpx.post(f"{base_url}/login", json={"email": admin_email, "password": password}, timeout=10.0)
    print(f"Pre-Verify Login Status Code: {login_res.status_code}")
    print(f"Pre-Verify Login Detail: {login_res.json()}")
    assert login_res.status_code == 403, "Login must return 403 Forbidden"
    assert login_res.json().get("detail") == "email_not_verified"

    print("\n[STEP 3] Fetching OTP Code from DB...")
    import sqlite3
    conn = sqlite3.connect("adaptivetrust.db")
    cursor = conn.cursor()
    cursor.execute("SELECT verification_code FROM users WHERE email = ?", (admin_email,))
    otp_code = cursor.fetchone()[0]
    conn.close()
    print(f"Fetched OTP Code from DB: {otp_code}")

    print("\n[STEP 4] Verifying Email via HTTP API...")
    verify_res = httpx.post(f"{base_url}/verify-email", json={"email": admin_email, "code": otp_code}, timeout=10.0)
    print(f"Verify Email Status Code: {verify_res.status_code}")
    print(f"Verify Email Response: {verify_res.json()}")
    assert verify_res.status_code == 200, "Verification must return 200 OK"

    print("\n[STEP 5] Logging in After Verification...")
    post_verify_login = httpx.post(f"{base_url}/login", json={"email": admin_email, "password": password}, timeout=10.0)
    print(f"Post-Verify Login Status Code: {post_verify_login.status_code}")
    print(f"Access Token Received: {post_verify_login.json().get('access_token')[:25]}...")
    assert post_verify_login.status_code == 200, "Login after verification must return 200 OK"

    print("\n=======================================================")
    print(" 🎉 FULL LOCAL WEB HTTP AUTHENTICATION FLOW PASSED 100%!")
    print("=======================================================\n")

if __name__ == "__main__":
    test_full_http_auth_flow()
