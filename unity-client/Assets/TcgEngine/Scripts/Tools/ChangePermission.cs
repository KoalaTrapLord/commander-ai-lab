using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;
using TcgEngine.UI;

namespace TcgEngine
{
    /// <summary>
    /// Use this tool to upload your cards and packs to the Mongo Database (it will overwrite existing data)
    /// </summary>

    public class ChangePermission : MonoBehaviour
    {
        public string username = "admin";

        [Header("Login")]
        public InputField username_txt;
        public InputField password_txt;

        [Header("Change Permission")]
        public UIPanel permission_panel;
        public InputField target_user_txt;
        public InputField target_perm_txt;
        public Text error;

        private string logged_user;

        void Start()
        {
            username_txt.text = username;
            error.text = "";
        }

        private async void Login(string user, string pass)
        {
            LoginResponse res = await ApiClient.Get().Login(user, pass);
            if (res.success && res.permission_level >= 10)
            {
                logged_user = user;
                permission_panel.Show();
            }
            else if (res.success)
            {
                error.text = "Not an admin user";
            }
            else
            {
                error.text = res.error;
            }
        }

        private async Task<string> GetUserID(string tuser)
        {
            string url = ApiClient.ServerURL + "/users/" + tuser;
            WebResponse res = await ApiClient.Get().SendGetRequest(url);
            UserData udata = ApiTool.JsonToObject<UserData>(res.data);
            if (!res.success)
                error.text = res.error;

            return res.success ? udata.id : null;
        }

        private async void SetPermission(string tuser, int permission)
        {
            string user_id = await GetUserID(tuser);
            if (user_id == null)
                return;

            ChangePermissionRequest req = new ChangePermissionRequest();
            req.permission_level = permission;

            string url = ApiClient.ServerURL + "/users/permission/edit/" + user_id;
            string json = ApiTool.ToJson(req);
            WebResponse res = await ApiClient.Get().SendPostRequest(url, json);

            if (!res.success)
                error.text = res.error;

            if (res.success)
            {
                error.text = "Success!";
                error.color = Color.green;
            }
        }

        public void OnClickLogin()
        {
            if (string.IsNullOrEmpty(username_txt.text))
                return;

            if (string.IsNullOrEmpty(password_txt.text))
                return;

            error.text = "";
            error.color = Color.red;
            Login(username_txt.text, password_txt.text);
        }

        public void OnClickUpdate()
        {
            if (string.IsNullOrEmpty(target_user_txt.text))
                return;

            bool success = int.TryParse(target_perm_txt.text, out int perm);
            if (!success)
                return;

            if (logged_user == target_user_txt.text)
                return; //Prevent changing yourself

            error.text = "";
            error.color = Color.red;
            SetPermission(target_user_txt.text, perm);
        }
    }

    [System.Serializable]
    public class ChangePermissionRequest
    {
        public int permission_level;
    }

}
