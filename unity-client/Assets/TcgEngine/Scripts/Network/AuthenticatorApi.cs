using System.Collections;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;

namespace TcgEngine
{
    /// <summary>
    /// This authenticator require external UserLogin API asset
    /// It works with an actual web API and database containing all user info
    /// </summary>

    public class AuthenticatorApi : Authenticator
    {
        private int permission = 0;

        public override async Task Initialize()
        {
            await base.Initialize();
        }

        public override async Task<bool> Login(string username, string password)
        {
            LoginResponse res = await Client.Login(username, password);
            if (res.success)
            {
                this.logged_in = true;
                this.user_id = res.id;
                this.username = res.username;
                permission = res.permission_level;
            }
            return res.success;
        }

        public override async Task<bool> RefreshLogin()
        {
            LoginResponse res = await Client.RefreshLogin();
            if (res.success)
            {
                this.logged_in = true;
                this.user_id = res.id;
                this.username = res.username;
            }
            return res.success;
        }

        public override async Task<bool> Register(string username, string email, string password)
        {
            RegisterResponse res = await Client.Register(username, email, password);

            if (res.success)
                await Login(username, password);

            return res.success;
        }

        public override async Task<UserData> LoadUserData()
        {
            UserData res = await Client.LoadUserData();
            return res;
        }

        public override async Task<bool> SaveUserData()
        {
            //Do nothing, saved on each api request, no need to save to disk
            await Task.Yield();
            return false;
        }

        public override void Logout()
        {
            base.Logout();
            Client.Logout();
            permission = 0;
        }

        public override UserData GetUserData()
        {
            return Client.UserData;
        }

        public override bool IsSignedIn()
        {
            return Client.IsLoggedIn();
        }

        public override bool IsExpired()
        {
            return Client.IsExpired();
        }

        public override int GetPermission()
        {
            return permission;
        }

        public override string GetError()
        {
            return Client.GetLastError();
        }

        public ApiClient Client { get { return ApiClient.Get(); } }

    }
}
