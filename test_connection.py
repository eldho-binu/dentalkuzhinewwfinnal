import requests
import sys

def test_backend():
    base_url = "http://127.0.0.1:5000"
    
    print("🧪 Testing backend connection...")
    
    # Test health endpoint
    try:
        response = requests.get(f"{base_url}/api/health", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Health check passed: {data}")
            
            if data.get('db_connected'):
                print("✅ Database connection confirmed")
            else:
                print("❌ Database connection failed")
                return False
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Cannot connect to backend: {e}")
        return False
    
    # Test login
    try:
        login_data = {"username": "admin", "password": "admin123"}
        response = requests.post(
            f"{base_url}/api/auth/login",
            json=login_data,
            timeout=10
        )
        
        if response.status_code == 200:
            print("✅ Login test passed")
            return True
        else:
            print(f"❌ Login test failed: {response.status_code}")
            print(f"Error: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Login test error: {e}")
        return False

if __name__ == "__main__":
    if test_backend():
        print("🎉 All tests passed!")
        sys.exit(0)
    else:
        print("💥 Tests failed!")
        sys.exit(1)