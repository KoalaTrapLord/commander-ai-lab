using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System.Threading.Tasks;
using UnityEngine.Networking;
using UnityEngine.Events;

namespace TcgEngine
{
    /// <summary>
    /// API client communicates with the NodeJS web api
    /// Can send requests and receive responses
    /// </summary>

    public class ApiClient : MonoBehaviour
    {
        public bool is_server;

        public UnityAction<RegisterResponse> onRegister; //Triggered after register, even if failed
        public UnityAction<LoginResponse> onLogin; //Triggered after login, even if failed
        public UnityAction<LoginResponse> onRefresh; //Triggered after login refresh, even if failed 
        public UnityAction onLogout; //Triggered after logout

        private string user_id = "";
        private string username = "";
        private string access_token = "";
        private string refresh_token = "";
        private string api_version = "";

        private bool logged_in = false;
        private bool expired = false;

        private UserData udata = null;

        private int sending = 0;
        private string last_error = "";
        private float refresh_timer = 0f;
        private float online_timer = 0f;
        private long expiration_timestamp = 0;

        private const float online_duration = 60f * 5f; //5 min

        private static ApiClient instance;

        void Awake()
        {
            //API client should be on OnDestroyOnLoad
            //dont assign here if already assigned cause new one will be destroyed in TheNetwork Awake
            if(instance == null)
                instance = this;

            LoadTokens();
        }

        private void Update()
        {
            //Refresh access token or online status
            Refresh();
        }

        private void LoadTokens()
        {
            if (!is_server && string.IsNullOrEmpty(user_id))
            {
                access_token = PlayerPrefs.GetString("tcg_access_token");
                refresh_token = PlayerPrefs.GetString("tcg_refresh_token");
            }
        }

        private void SaveTokens()
        {
            if (!is_server)
            {
                PlayerPrefs.SetString("tcg_access_token", access_token);
                PlayerPrefs.SetString("tcg_refresh_token", refresh_token);
            }
        }

        private async void Refresh()
        {
            if (!logged_in)
                return;

            //Check expiration
            if (!expired)
            {
                long current = GetTimestamp();
                expired = current > (expiration_timestamp - 10);
            }

            //Refresh access token when expired
            refresh_timer += Time.deltaTime;
            if (expired && refresh_timer > 5f)
            {
                refresh_timer = 0f;
                await RefreshLogin(); //Try to relogin
            }

            //Refresh online status
            online_timer += Time.deltaTime;
            if (!expired && online_timer > online_duration)
            {
                online_timer = 0f;
                await KeepOnline();
            }
        }

        public async Task<RegisterResponse> Register(string email, string user, string password)
        {
            RegisterRequest data = new RegisterRequest();
            data.email = email;
            data.username = user;
            data.password = password;
            data.avatar = "";
            return await Register(data);
        }

        public async Task<RegisterResponse> Register(RegisterRequest data)
        {
            Logout(); //Disconnect

            string url = ServerURL + "/users/register";
            string json = ApiTool.ToJson(data);

            WebResponse res = await SendPostRequest(url, json);
            RegisterResponse regist_res = ApiTool.JsonToObject<RegisterResponse>(res.data);
            regist_res.success = res.success;
            regist_res.error = res.error;
            onRegister?.Invoke(regist_res);
            return regist_res;
        }

        public async Task<LoginResponse> Login(string user, string password)
        {
            Logout(); //Disconnect

            LoginRequest data = new LoginRequest();
            data.password = password;

            if (user.Contains("@"))
                data.email = user;
            else
                data.username = user;

            string url = ServerURL + "/auth";
            string json = ApiTool.ToJson(data);

            WebResponse res = await SendPostRequest(url, json);
            LoginResponse login_res = GetLoginRes(res);
            AfterLogin(login_res);

            onLogin?.Invoke(login_res);
            return login_res;
        }

        public async Task<LoginResponse> RefreshLogin()
        {
            string url = ServerURL + "/auth/refresh";
            AutoLoginRequest data = new AutoLoginRequest();
            data.refresh_token = refresh_token;
            string json = ApiTool.ToJson(data);

            WebResponse res = await SendPostRequest(url, json);
            LoginResponse login_res = GetLoginRes(res);
            AfterLogin(login_res);

            onRefresh?.Invoke(login_res);
            return login_res;
        }

        private LoginResponse GetLoginRes(WebResponse res)
        {
            LoginResponse login_res = ApiTool.JsonToObject<LoginResponse>(res.data);
            login_res.success = res.success;
            login_res.error = res.error;

            //Uncomment to force having same client version as api
            /*if (!is_server && !IsVersionValid())
            {
                login_res.error = "Invalid Version";
                login_res.success = false;
            }*/

            return login_res;
        }

        private void AfterLogin(LoginResponse login_res)
        {
            last_error = login_res.error;

            if (login_res.success)
            {
                user_id = login_res.id;
                username = login_res.username;
                access_token = login_res.access_token;
                refresh_token = login_res.refresh_token;
                api_version = login_res.version;
                expiration_timestamp = GetTimestamp() + login_res.duration;
                refresh_timer = 0f;
                online_timer = 0f;
                logged_in = true;
                expired = false;
                SaveTokens();
            }
        }

        public async Task<UserData> LoadUserData()
        {
            udata = await LoadUserData(this.username);
            return udata;
        }

        public async Task<UserData> LoadUserData(string username)
        {
            if (!IsConnected())
                return null;

            string url = ServerURL + "/users/" + username;
            WebResponse res = await SendGetRequest(url);

            UserData udata = null;
            if (res.success)
            {
                udata = ApiTool.JsonToObject<UserData>(res.data);
            }

            return udata;
        }

        public async Task<bool> KeepOnline()
        {
            if (!IsConnected())
                return false;

            //Keep player online
            string url = ServerURL + "/auth/keep";
            WebResponse res = await SendGetRequest(url);
            expired = !res.success;
            return res.success;
        }

        public async Task<bool> Validate()
        {
            if (!IsConnected())
                return false;

            //Check if connection is still valid
            string url = ServerURL + "/auth/validate";
            WebResponse res = await SendGetRequest(url);
            expired = !res.success;
            return res.success;
        }

        public void Logout()
        {
            user_id = "";
            username = "";
            access_token = "";
            refresh_token = "";
            api_version = "";
            last_error = "";
            logged_in = false;
            onLogout?.Invoke();
            SaveTokens();
        }

        public async void CreateMatch(Game game_data)
        {
            if (game_data.settings.game_type != GameType.Multiplayer)
                return;

            AddMatchRequest req = new AddMatchRequest();
            req.players = new string[2];
            req.players[0] = game_data.players[0].username;
            req.players[1] = game_data.players[1].username;
            req.tid = game_data.game_uid;
            req.ranked = game_data.settings.IsRanked();
            req.mode = game_data.settings.GetGameModeId();

            string url = ServerURL + "/matches/add";
            string json = ApiTool.ToJson(req);
            WebResponse res = await SendPostRequest(url, json);
            Debug.Log("Match Started! " + res.success);
        }

        public async void EndMatch(Game game_data, int winner_id)
        {
            if (game_data.settings.game_type != GameType.Multiplayer)
                return;

            Player player = game_data.GetPlayer(winner_id);
            CompleteMatchRequest req = new CompleteMatchRequest();
            req.tid = game_data.game_uid;
            req.winner = player != null ? player.username : "";

            string url = ServerURL + "/matches/complete";
            string json = ApiTool.ToJson(req);
            WebResponse res = await SendPostRequest(url, json);
            Debug.Log("Match Completed! " + res.success);
        }

        public async Task<string> SendGetVersion()
        {
            string url = ServerURL + "/version";
            WebResponse res = await SendGetRequest(url);

            if (res.success)
            {
                VersionResponse version_data = ApiTool.JsonToObject<VersionResponse>(res.data);
                api_version = version_data.version;
                return api_version;
            }

            return null;
        }

        public async Task<WebResponse> SendGetRequest(string url)
        {
            return await SendRequest(url, WebRequest.METHOD_GET);
        }

        public async Task<WebResponse> SendPostRequest(string url, string json_data)
        {
            return await SendRequest(url, WebRequest.METHOD_POST, json_data);
        }

        public async Task<WebResponse> SendRequest(string url, string method, string json_data = "")
        {
            UnityWebRequest request = WebRequest.Create(url, method, json_data, access_token);
            return await SendRequest(request);
        }

        private async Task<WebResponse> SendRequest(UnityWebRequest request)
        {
            int wait = 0;
            int wait_max = request.timeout * 1000;
            request.timeout += 1; //Add offset to make sure it aborts first
            sending++;

            var async_oper = request.SendWebRequest();
            while (!async_oper.isDone)
            {
                await TimeTool.Delay(200);
                wait += 200;
                if (wait >= wait_max)
                    request.Abort(); //Abort to avoid unity errors on timeout
            }

            WebResponse response = WebRequest.GetResponse(request);
            response.error = GetError(response);
            last_error = response.error;
            request.Dispose();
            sending--;

            return response;
        }

        private string GetError(WebResponse res)
        {
            if (res.success)
                return "";

            ErrorResponse err = ApiTool.JsonToObject<ErrorResponse>(res.data);
            if (err != null)
                return err.error;
            else
                return res.error;
        }

        public bool IsConnected()
        {
            return logged_in && !expired;
        }

        public bool IsLoggedIn()
        {
            return logged_in;
        }

        public bool IsExpired()
        {
            return expired;
        }

        public bool IsBusy()
        {
            return sending > 0;
        }

        public long GetTimestamp()
        {
            return System.DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        }

        public string GetLastRequest()
        {
            return last_error;
        }

        public string GetLastError()
        {
            return last_error;
        }

        //Use this function if you want to prevent players to login with an outdated client
        //Call it inside the login and loginrefresh functions after the api_version is set and return error if invalid
        public bool IsVersionValid()
        {
            return ClientVersion == ServerVersion; 
        }

        public UserData UserData { get { return udata; } }

        public string UserID { get { return user_id; } set { user_id = value; } }
        public string Username { get { return username; } set { username = value; } }
        public string AccessToken { get { return access_token; } set { access_token = value; } }
        public string RefreshToken { get { return refresh_token; } set { refresh_token = value; } }

        public string ServerVersion { get { return api_version; } }
        public string ClientVersion { get { return Application.version; } }

        public static string ServerURL
        {
            get
            {
                NetworkData data = NetworkData.Get();
                string protocol = data.api_https ? "https://" : "http://";
                return protocol + data.api_url;
            }
        }

        public static ApiClient Get()
        {
            if (instance == null)
                instance = FindObjectOfType<ApiClient>();
            return instance;
        }
    }
}
