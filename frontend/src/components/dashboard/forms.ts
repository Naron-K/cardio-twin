/** The three forms the dashboard's twin zone can take. */
export type TwinForm = 'animation' | 'graph' | 'table'
export const TWIN_FORMS: TwinForm[] = ['animation', 'graph', 'table']

/** The older screens, still reachable until the dashboard replaces them. */
export type OtherScreen = 'twin' | 'body' | 'analysis' | 'stream'
