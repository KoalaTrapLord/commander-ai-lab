var FileUploadPlugin = {
    _objectName: null,
    _methodName: null,
    _fileInput: null,

    WebGLFileUploadInit: function (objectNamePtr, methodNamePtr) {
        this._objectName = UTF8ToString(objectNamePtr);
        this._methodName = UTF8ToString(methodNamePtr);

        if (!this._fileInput) {
            this._fileInput = document.createElement('input');
            this._fileInput.type = 'file';
            this._fileInput.accept = 'image/*';
            this._fileInput.style.display = 'none';
            document.body.appendChild(this._fileInput);

            var self = this;
            this._fileInput.addEventListener('change', function (e) {
                var file = e.target.files[0];
                if (!file) return;

                var reader = new FileReader();
                reader.onload = function (evt) {
                    var base64 = evt.target.result.split(',')[1];
                    SendMessage(self._objectName, self._methodName, base64);
                };
                reader.readAsDataURL(file);
                e.target.value = '';
            });
        }
    },

    WebGLFileUploadClick: function () {
        if (this._fileInput) {
            this._fileInput.click();
        }
    }
};

mergeInto(LibraryManager.library, FileUploadPlugin);
