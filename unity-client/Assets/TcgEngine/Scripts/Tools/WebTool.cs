using System.Collections.Generic;
using System.Text;
using UnityEngine.Networking;
using System;
using UnityEngine;
using System.Net;
using System.IO;
using System.Collections;
using System.Threading.Tasks;

namespace TcgEngine
{
    /// <summary>
    /// Tool to send HTTP web resquests
    /// </summary>

    public class WebRequest
    {
        public const string METHOD_GET = "GET";
        public const string METHOD_POST = "POST";
        public const string METHOD_PATCH = "PATCH";
        public const string METHOD_DELETE = "DELETE";
        public const int timeout = 10;

        public static UnityWebRequest Create(string url)
        {
            UnityWebRequest request = new UnityWebRequest(url, METHOD_GET);
            request.SetRequestHeader("Content-Type", "application/json");
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = timeout;
            return request;
        }

        public static UnityWebRequest Create(string url, string method, string json_data, string token)
        {
            UnityWebRequest request = new UnityWebRequest(url, method);
            request.SetRequestHeader("Content-Type", "application/json");
            if(token != null)
                request.SetRequestHeader("Authorization", token);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = timeout;

            if (method != METHOD_GET && !string.IsNullOrEmpty(json_data))
            {
                UploadHandler uploader = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json_data));
                uploader.contentType = "application/json";
                request.uploadHandler = uploader;
            }

            return request;
        }

        public static UnityWebRequest CreateRaw(string url, string method, string contentType, byte[] data, string token)
        {
            UnityWebRequest request = new UnityWebRequest(url, method);
            request.SetRequestHeader("Content-Type", contentType);
            if (token != null)
                request.SetRequestHeader("Authorization", token);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = timeout;

            if (method != METHOD_GET && !string.IsNullOrEmpty(contentType))
            {
                UploadHandler uploader = new UploadHandlerRaw(data);
                uploader.contentType = contentType;
                request.uploadHandler = uploader;
            }

            return request;
        }

        public static UnityWebRequest CreateHeader(string url)
        {
            UnityWebRequest request = UnityWebRequest.Head(url);
            return request;
        }

        public static UnityWebRequest CreateTexture(string url)
        {
            UnityWebRequest request = UnityWebRequestTexture.GetTexture(url);
            request.SetRequestHeader("Content-Type", "image/png");
            return request;
        }

        public static UnityWebRequest CreateImageUploadForm(string url, string path, byte[] data, string token)
        {
            List<IMultipartFormSection> requestData = new List<IMultipartFormSection>();
            requestData.Add(new MultipartFormDataSection("path", path, "text"));
            requestData.Add(new MultipartFormFileSection("data", data, "file.png", "image/png"));

            UnityWebRequest request = UnityWebRequest.Post(url, requestData);
            if (token != null)
                request.SetRequestHeader("Authorization", token);
            request.timeout = 200;

            return request;
        }

        public static WebResponse GetResponse(UnityWebRequest request)
        {
            WebResponse res = new WebResponse();
            res.success = request.responseCode >= 200 && request.responseCode < 300;
            res.status = request.responseCode;
            res.error = request.error;
            res.data = "";
            if (request.downloadHandler != null)
                res.data = request.downloadHandler.text;
            return res;
        }

        public static HeadResponse GetHeadResponse(UnityWebRequest request)
        {

            HeadResponse res = new HeadResponse();
            res.success = request.responseCode >= 200 && request.responseCode < 300;
            res.status = request.responseCode;

            string type = request.GetResponseHeader("Content-Type");
            DateTime.TryParse(request.GetResponseHeader("Last-Modified"), out DateTime date);
            int.TryParse(request.GetResponseHeader("Content-Length"), out int size);

            res.content_type = type;
            res.last_edit = date;
            res.size = size;

            return res;
        }
    }

    public class WebTool
    {
        public static T JsonToObject<T>(string json)
        {
            T value = (T)Activator.CreateInstance(typeof(T));
            try
            {
                value = JsonUtility.FromJson<T>(json);
            }
            catch (Exception) { }
            return value;
        }

        public static T[] JsonToArray<T>(string json)
        {
            ListJson<T> list = new ListJson<T>();
            list.list = new T[0];
            try
            {
                string wrap_json = "{ \"list\": " + json + "}";
                list = JsonUtility.FromJson<ListJson<T>>(wrap_json);
                return list.list;
            }
            catch (Exception) { }
            return new T[0];
        }

        public static string ToJson(object data)
        {
            return JsonUtility.ToJson(data);
        }

        public static int Parse(string int_str, int default_val = 0)
        {
            bool success = int.TryParse(int_str, out int val);
            return success ? val : default_val;
        }

        public static async Task<WebResponse> SendRequest(string url)
        {
            UnityWebRequest req = WebRequest.Create(url);
            return await SendRequest(req);
        }

        public static async Task<WebResponse> SendRequest(UnityWebRequest request)
        {
            try
            {
                var asyncOp = request.SendWebRequest();
                while (!asyncOp.isDone)
                    await TimeTool.Delay(200);
            }
            catch (Exception) {}

            if (request.result != UnityWebRequest.Result.Success)
                Debug.Log(request.error);

            WebResponse res = WebRequest.GetResponse(request);
			request.Dispose();

            return res;
        }
    }

    public class WebContext
    {
        public HttpListenerContext http;
        public string method;
        public string token;
        public string path;
        public string data;

        public void SendResponse<T>(T value)
        {
            string val = WebTool.ToJson(value);
            SendResponse(val);
        }

        public void SendResponse(ulong value)
        {
            SendResponse(value.ToString());
        }

        public void SendResponse(int value)
        {
            SendResponse(value.ToString());
        }

        public void SendResponse(bool value)
        {
            SendResponse(value.ToString());
        }

        public void SendResponse(string value)
        {
            byte[] bytes = System.Text.Encoding.UTF8.GetBytes(value);
            SendResponse(bytes, 200);
        }

        public void SendError(string value)
        {
            byte[] bytes = System.Text.Encoding.UTF8.GetBytes(value);
            SendResponse(bytes, 400);
        }

        public void SendResponse()
        {
            try
            {
                WriteHeader();
                http.Response.StatusCode = 200;
                http.Response.Close();
            }
            catch (Exception e) { Debug.Log(e); }
        }
        
        public void SendResponse(byte[] bytes, int code)
        {
            try
            {
                WriteHeader();
                http.Response.StatusCode = code;
                http.Response.OutputStream.Write(bytes, 0, bytes.Length);
                http.Response.Close();
            }
            catch (Exception e) { Debug.Log(e); }
        }

        private void WriteHeader()
        {
            http.Response.Headers.Add("Access-Control-Allow-Origin", "*");
            http.Response.Headers.Add("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS,POST,PUT");
            http.Response.Headers.Add("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization");
        }

        public T GetData<T>()
        {
            return WebTool.JsonToObject<T>(data);
        }

        public ulong GetInt64()
        {
            bool valid = ulong.TryParse(data, out ulong val);
            return valid ? val : 0;
        }

        public int GetInt()
        {
            bool valid = int.TryParse(data, out int val);
            return valid ? val : 0;
        }

        public bool GetBool()
        {
            bool valid = bool.TryParse(data, out bool val);
            return valid ? val : false;
        }

        public ulong GetClientID()
        {
            bool valid = ulong.TryParse(token, out ulong val);
            return valid ? val : 0;
        }

        public string GetIP()
        {
            return http.Request.RemoteEndPoint.Address.ToString();
        }

        public string GetKey()
        {
            return token;
        }

        public bool IsKeyValid(string key)
        {
            return token == key;
        }

        public string GetQuery(string key)
        {
            try
            {
                return http.Request.QueryString.Get(key);
            }
            catch (Exception e) { Debug.Log(e); }

            return "";
        }

        public void Close()
        {
            try
            {
                http.Response.Close();
            }
            catch (Exception e) { Debug.Log(e); }
        }

        public static WebContext Create(HttpListenerContext http)
        {
            WebContext req = new WebContext();
            req.http = http;
            req.path = "";
            req.data = "";

            try
            {
                req.method = http.Request.HttpMethod;
                req.path = http.Request.RawUrl.Remove(0, 1);
                req.token = http.Request.Headers.Get("Authorization");

                if (http.Request.InputStream != null)
                {
                    StreamReader reader = new StreamReader(http.Request.InputStream, http.Request.ContentEncoding);
                    req.data = reader.ReadToEnd();
                }
            }
            catch (Exception e) { Debug.Log(e);  }

            return req;
        }
    }

    public struct WebResponse
    {
        public bool success;
        public long status;
        public string data;
        public string error;

        public ulong GetInt64()
        {
            bool valid = ulong.TryParse(data, out ulong val);
            return valid ? val : 0;
        }

        public int GetInt()
        {
            bool valid = int.TryParse(data, out int val);
            return valid ? val : 0;
        }

        public bool GetBool()
        {
            bool valid = bool.TryParse(data, out bool val);
            return valid ? val : false;
        }

        public T GetData<T>()
        {
            return WebTool.JsonToObject<T>(data);
        }
		
		public string GetError()
        {
            ErrorResponse err = WebTool.JsonToObject<ErrorResponse>(data);
            if(err != null)
                return err.error;
            return error;
        }
    }

    public class HeadResponse
    {
        public bool success;
        public long status;
        public DateTime last_edit;
        public int size;
        public string content_type;
    }


    [Serializable]
    public class ErrorResponse
    {
        public string error;
    }

    [Serializable]
    public class ListJson<T>
    {
        public T[] list;
        public string error;
    }
}