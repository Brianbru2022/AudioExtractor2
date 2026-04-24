import { open } from '@tauri-apps/plugin-dialog'
import { getCurrentWindow } from '@tauri-apps/api/window'

export async function selectSourceFile() {
  try {
    const result = await open({
      multiple: false,
      filters: [
        {
          name: 'Meeting media',
          extensions: ['wav', 'mp3', 'm4a', 'flac', 'mp4', 'mov', 'mkv'],
        },
      ],
    })

    return typeof result === 'string' ? result : null
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    throw new Error(`Tauri file dialog is unavailable. ${message}`)
  }
}

export async function selectDirectory() {
  try {
    const result = await open({
      directory: true,
      multiple: false,
    })

    return typeof result === 'string' ? result : null
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    throw new Error(`Tauri directory dialog is unavailable. ${message}`)
  }
}

export function subscribeToFileDrops(callback: (paths: string[]) => void) {
  const currentWindow = getCurrentWindow()
  return currentWindow.onDragDropEvent((event) => {
    if (event.payload.type === 'drop') {
      callback(event.payload.paths)
    }
  })
}
