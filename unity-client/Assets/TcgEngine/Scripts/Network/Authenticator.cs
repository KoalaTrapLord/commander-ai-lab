using System.Collections;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// Base class for all Authenticators, must be inherited
    /// </summary>

    public abstract class Authenticator
    {
        protected string user_id = null;
        protected string username = null;
        protected bool logged_in = false;
        protected bool inited = false;

        public virtual async Task Initialize()
        {
            inited = true;
            await Task.Yield(); //Do nothing
        }

        public virtual async Task<bool> Login(string username)
        {
            await Task.Yield(); //Do nothing
            return false;
        }

        public virtual async Task<bool> Login(string username, string token)
        {
            return await Login(username); //Some authenticator dont define this function
        }

        public virtual async Task<bool> RefreshLogin()
        {
            return await Login(username); //Same as Login if not defined
        }

        //Bypass login system by just assigning your own values, for testing
        public virtual void LoginTest(string username)
        {
            this.user_id = username;
            this.username = username;
            logged_in = true;
        }

        public virtual async Task<bool> Register(string username, string email, string token)
        {
            return await Login(username, token); //Some authenticator dont define this function
        }

        public virtual async Task<UserData> LoadUserData()
        {
            await Task.Yield(); //Do nothing
            return null;
        }

        public virtual async Task<bool> SaveUserData()
        {
            await Task.Yield(); //Do nothing
            return false;
        }

        public virtual void Logout()
        {
            logged_in = false;
            user_id = null;
            username = null;
        }

        public virtual bool IsInited()
        {
            return inited;
        }

        public virtual bool IsConnected()
        {
            return IsSignedIn() && !IsExpired();
        }

        public virtual bool IsSignedIn()
        {
            return logged_in; //IsSignedIn will still be true if the login expires
        }

        public virtual bool IsExpired()
        {
            return false;
        }

        public virtual string GetUserId()
        {
            return user_id;
        }

        public virtual string GetUsername()
        {
            return username;
        }

        public virtual int GetPermission()
        {
            return logged_in ? 1 : 0;
        }

        public virtual UserData GetUserData()
        {
            return null;
        }

        public virtual string GetError()
        {
            return ""; //Should return the latest error
        }

        public bool IsTest()
        {
            return NetworkData.Get().auth_type == AuthenticatorType.LocalSave;
        }

        public bool IsApi()
        {
            return NetworkData.Get().auth_type == AuthenticatorType.Api;
        }

        public string UserID{ get{ return GetUserId(); }}
        public string Username{ get { return GetUsername(); } }
        public UserData UserData{ get { return GetUserData(); } }

        public static Authenticator Create(AuthenticatorType type)
        {
            if (type == AuthenticatorType.Api)
                return new AuthenticatorApi();
            else
                return new AuthenticatorLocal();
        }

        public static Authenticator Get()
        {
            return TcgNetwork.Get().Auth; //Access authenticator
        }
    }

    public enum AuthenticatorType
    {
        LocalSave = 0,   //Test Mode, Fake login for quick testing without the need to login each time
        Api = 10,        //Actual online login
    }
}