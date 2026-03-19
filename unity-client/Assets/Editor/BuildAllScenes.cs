#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class BuildAllScenes
{
    [MenuItem("Tools/Build All Scenes")]
    public static void BuildAll()
    {
        // Clear build settings first
        EditorBuildSettings.scenes = new EditorBuildSettingsScene[0];

        // Create all scenes in order (MainMenu must be index 0)
        CreateMainMenuScene.Create();
        CreateCollectionScene.Create();
        CreateDeckBuilderScene.Create();
        CreateSimulatorScene.Create();
        CreateScannerScene.Create();
        CreateTrainingScene.Create();

        // Log the final build settings
        Debug.Log($"[BuildAllScenes] Registered {EditorBuildSettings.scenes.Length} scenes in Build Settings:");
        foreach (var s in EditorBuildSettings.scenes)
            Debug.Log($"  {s.path} (enabled={s.enabled})");

        // Reopen MainMenu as the active scene
        EditorSceneManager.OpenScene("Assets/Scenes/MainMenu.unity");
        Debug.Log("[BuildAllScenes] Done! MainMenu scene is now active.");
    }
}
#endif
