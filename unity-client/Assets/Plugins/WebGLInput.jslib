var WebGLInput = {
  GetURLParam: function(keyPtr) {
    var key = UTF8ToString(keyPtr);
    var params = new URLSearchParams(window.location.search);
    var value = params.get(key) || '';
    var bufferSize = lengthBytesUTF8(value) + 1;
    var buffer = _malloc(bufferSize);
    stringToUTF8(value, buffer, bufferSize);
    return buffer;
  },

  OpenFileDialog: function(acceptPtr, callbackObjPtr, callbackMethodPtr) {
    var accept = UTF8ToString(acceptPtr);
    var callbackObj = UTF8ToString(callbackObjPtr);
    var callbackMethod = UTF8ToString(callbackMethodPtr);
    var input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.onchange = function(e) {
      var file = e.target.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function(ev) {
        var base64 = ev.target.result.split(',')[1];
        SendMessage(callbackObj, callbackMethod, base64);
      };
      reader.readAsDataURL(file);
    };
    input.click();
  },

  SetLoadingProgress: function(progress) {
    var bar = document.getElementById('unity-progress-bar-full');
    if (bar) bar.style.width = (progress * 100) + '%';
  }
};

mergeInto(LibraryManager.library, WebGLInput);
