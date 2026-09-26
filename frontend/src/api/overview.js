/** 概览接口封装（接口文档 §3.4）：概览页与侧栏「今日待办」共用。 */
import request from './request'

export const getOverviewApi = (config) => request.get('/overview', config)
