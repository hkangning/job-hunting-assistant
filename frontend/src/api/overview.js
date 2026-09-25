/** 概览接口封装（本步个人中心数据概览卡片取统计，步骤 9 扩充）。 */
import request from './request'

export const getOverviewApi = () => request.get('/overview')
