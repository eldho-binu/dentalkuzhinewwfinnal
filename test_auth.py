import requests
import json

def test_health():
    """Test if server is running"""
    try:
        response = requests.get('http://127.0.0.1:5000/api/health', timeout=5)
        print(f"🏥 Health check: {response.status_code}")
        if response.status_code == 200:
            print(f"✅ Server is running: {response.json()}")
            return True
        else:
            print(f"❌ Server health check failed")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Cannot connect to server: {e}")
        return False

def test_login():
    """Test login and get token"""
    # First check if server is running
    if not test_health():
        return None
    
    login_data = {
        "username": "admin",
        "password": "admin123"
    }
    
    print(f"\n🔐 Testing login with data: {login_data}")
    
    try:
        response = requests.post(
            'http://127.0.0.1:5000/api/auth/login',
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            json=login_data,
            timeout=10
        )
        
        print(f"📊 Response status: {response.status_code}")
        print(f"📋 Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Login successful!")
            print(f"📄 Full response: {json.dumps(data, indent=2)}")
            
            token = data.get('token')
            if token:
                print(f"🎫 Token received: {token[:20]}...")
                return token
            else:
                print(f"❌ No token in response")
                return None
        else:
            print(f"❌ Login failed with status {response.status_code}")
            try:
                error_data = response.json()
                print(f"📄 Error response: {json.dumps(error_data, indent=2)}")
            except:
                print(f"📄 Raw error response: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode error: {e}")
        print(f"📄 Raw response: {response.text}")
        return None

def test_debug_auth(token):
    """Test debug auth endpoint"""
    if not token:
        print("❌ No token provided for debug")
        return
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    print(f"\n🔬 Testing DEBUG auth endpoint")
    
    try:
        response = requests.get(
            'http://127.0.0.1:5000/api/auth/debug',
            headers=headers,
            timeout=10
        )
        
        print(f"📊 Debug response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📄 Debug response: {json.dumps(data, indent=2)}")
        else:
            print(f"❌ Debug request failed with status {response.status_code}")
            try:
                error_data = response.json()
                print(f"📄 Error response: {json.dumps(error_data, indent=2)}")
            except:
                print(f"📄 Raw error response: {response.text}")
                
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")

def test_auth_check(token=None):
    """Test auth check endpoint"""
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    if token:
        headers['Authorization'] = f'Bearer {token}'
        print(f"\n🔍 Testing auth check WITH token")
    else:
        print(f"\n🔍 Testing auth check WITHOUT token")
    
    try:
        response = requests.get(
            'http://127.0.0.1:5000/api/auth/check',
            headers=headers,
            timeout=10
        )
        
        print(f"📊 Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📄 Auth check response: {json.dumps(data, indent=2)}")
            
            if data.get('authenticated'):
                print("✅ Authentication verified")
            else:
                print("❌ Not authenticated")
        else:
            print(f"❌ Auth check failed with status {response.status_code}")
            try:
                error_data = response.json()
                print(f"📄 Error response: {json.dumps(error_data, indent=2)}")
            except:
                print(f"📄 Raw error response: {response.text}")
                
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")

def test_authenticated_request(token):
    """Test authenticated request"""
    if not token:
        print("❌ No token provided")
        return
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    print(f"\n🔍 Testing authenticated request to dashboard stats")
    
    try:
        response = requests.get(
            'http://127.0.0.1:5000/api/dashboard/stats',
            headers=headers,
            timeout=10
        )
        
        print(f"📊 Response status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Authenticated request successful")
            data = response.json()
            print(f"📊 Total patients: {data.get('total_patients', 'N/A')}")
        else:
            print(f"❌ Authenticated request failed with status {response.status_code}")
                
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    print("🧪 Starting Authentication Tests...")
    print("=" * 50)
    
    # Test 1: Health check and login
    print("\n1️⃣ Testing server health and login...")
    token = test_login()
    
    # Test 2: Debug auth (new test)
    if token:
        print("\n2️⃣ Testing DEBUG auth endpoint...")
        test_debug_auth(token)
        
        print("\n3️⃣ Testing auth check with token...")
        test_auth_check(token)
        
        print("\n4️⃣ Testing dashboard stats with token...")
        test_authenticated_request(token)
    
    # Test 5: Auth check without token
    print("\n5️⃣ Testing auth check without token...")
    test_auth_check()
    
    print("\n" + "=" * 50)
    print("🏁 Tests completed!")