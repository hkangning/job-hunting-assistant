// 全国省市选项（省 → 地级市 两级），供投递的城市级联选择使用（筛选与表单共用同一份）。
//
// 数据来源：element-china-area-data@6.1.0 的 pcaTextArr，取其**第二级**，
// 构建期提取一次后内嵌，运行时不含该依赖。三条口径：
//   1. value 去掉尾部「市」字——库内既有数据存的是「南京」而非「南京市」，
//      不去后缀会让选择结果与历史数据分裂成两个筛选条件；
//   2. 第二级只到**地级市**（含自治州 / 地区 / 盟），不含县级市（昆山、常熟等）。
//      pcaTextArr 的第二级本身即地级市，另需排除 label 含「直辖县级行政区划」的
//      占位项（河南 / 湖北 / 海南 / 新疆各 1 项）；
//   3. 直辖市不设第二级（其下辖是「区」，市一级就是它自己），选中即一级。
//
// 重新生成：数据源升级或粒度调整时，按上述三条口径从 pcaTextArr 第二级重新提取即可。

export const CITY_OPTIONS = [
  { value: '北京', label: '北京市' },
  { value: '天津', label: '天津市' },
  {
    value: '河北省',
    label: '河北省',
    children: [
    { value: '石家庄', label: '石家庄市' },
    { value: '唐山', label: '唐山市' },
    { value: '秦皇岛', label: '秦皇岛市' },
    { value: '邯郸', label: '邯郸市' },
    { value: '邢台', label: '邢台市' },
    { value: '保定', label: '保定市' },
    { value: '张家口', label: '张家口市' },
    { value: '承德', label: '承德市' },
    { value: '沧州', label: '沧州市' },
    { value: '廊坊', label: '廊坊市' },
    { value: '衡水', label: '衡水市' }
    ]
  },
  {
    value: '山西省',
    label: '山西省',
    children: [
    { value: '太原', label: '太原市' },
    { value: '大同', label: '大同市' },
    { value: '阳泉', label: '阳泉市' },
    { value: '长治', label: '长治市' },
    { value: '晋城', label: '晋城市' },
    { value: '朔州', label: '朔州市' },
    { value: '晋中', label: '晋中市' },
    { value: '运城', label: '运城市' },
    { value: '忻州', label: '忻州市' },
    { value: '临汾', label: '临汾市' },
    { value: '吕梁', label: '吕梁市' }
    ]
  },
  {
    value: '内蒙古自治区',
    label: '内蒙古自治区',
    children: [
    { value: '呼和浩特', label: '呼和浩特市' },
    { value: '包头', label: '包头市' },
    { value: '乌海', label: '乌海市' },
    { value: '赤峰', label: '赤峰市' },
    { value: '通辽', label: '通辽市' },
    { value: '鄂尔多斯', label: '鄂尔多斯市' },
    { value: '呼伦贝尔', label: '呼伦贝尔市' },
    { value: '巴彦淖尔', label: '巴彦淖尔市' },
    { value: '乌兰察布', label: '乌兰察布市' },
    { value: '兴安盟', label: '兴安盟' },
    { value: '锡林郭勒盟', label: '锡林郭勒盟' },
    { value: '阿拉善盟', label: '阿拉善盟' }
    ]
  },
  {
    value: '辽宁省',
    label: '辽宁省',
    children: [
    { value: '沈阳', label: '沈阳市' },
    { value: '大连', label: '大连市' },
    { value: '鞍山', label: '鞍山市' },
    { value: '抚顺', label: '抚顺市' },
    { value: '本溪', label: '本溪市' },
    { value: '丹东', label: '丹东市' },
    { value: '锦州', label: '锦州市' },
    { value: '营口', label: '营口市' },
    { value: '阜新', label: '阜新市' },
    { value: '辽阳', label: '辽阳市' },
    { value: '盘锦', label: '盘锦市' },
    { value: '铁岭', label: '铁岭市' },
    { value: '朝阳', label: '朝阳市' },
    { value: '葫芦岛', label: '葫芦岛市' }
    ]
  },
  {
    value: '吉林省',
    label: '吉林省',
    children: [
    { value: '长春', label: '长春市' },
    { value: '吉林', label: '吉林市' },
    { value: '四平', label: '四平市' },
    { value: '辽源', label: '辽源市' },
    { value: '通化', label: '通化市' },
    { value: '白山', label: '白山市' },
    { value: '松原', label: '松原市' },
    { value: '白城', label: '白城市' },
    { value: '延边朝鲜族自治州', label: '延边朝鲜族自治州' }
    ]
  },
  {
    value: '黑龙江省',
    label: '黑龙江省',
    children: [
    { value: '哈尔滨', label: '哈尔滨市' },
    { value: '齐齐哈尔', label: '齐齐哈尔市' },
    { value: '鸡西', label: '鸡西市' },
    { value: '鹤岗', label: '鹤岗市' },
    { value: '双鸭山', label: '双鸭山市' },
    { value: '大庆', label: '大庆市' },
    { value: '伊春', label: '伊春市' },
    { value: '佳木斯', label: '佳木斯市' },
    { value: '七台河', label: '七台河市' },
    { value: '牡丹江', label: '牡丹江市' },
    { value: '黑河', label: '黑河市' },
    { value: '绥化', label: '绥化市' },
    { value: '大兴安岭地区', label: '大兴安岭地区' }
    ]
  },
  { value: '上海', label: '上海市' },
  {
    value: '江苏省',
    label: '江苏省',
    children: [
    { value: '南京', label: '南京市' },
    { value: '无锡', label: '无锡市' },
    { value: '徐州', label: '徐州市' },
    { value: '常州', label: '常州市' },
    { value: '苏州', label: '苏州市' },
    { value: '南通', label: '南通市' },
    { value: '连云港', label: '连云港市' },
    { value: '淮安', label: '淮安市' },
    { value: '盐城', label: '盐城市' },
    { value: '扬州', label: '扬州市' },
    { value: '镇江', label: '镇江市' },
    { value: '泰州', label: '泰州市' },
    { value: '宿迁', label: '宿迁市' }
    ]
  },
  {
    value: '浙江省',
    label: '浙江省',
    children: [
    { value: '杭州', label: '杭州市' },
    { value: '宁波', label: '宁波市' },
    { value: '温州', label: '温州市' },
    { value: '嘉兴', label: '嘉兴市' },
    { value: '湖州', label: '湖州市' },
    { value: '绍兴', label: '绍兴市' },
    { value: '金华', label: '金华市' },
    { value: '衢州', label: '衢州市' },
    { value: '舟山', label: '舟山市' },
    { value: '台州', label: '台州市' },
    { value: '丽水', label: '丽水市' }
    ]
  },
  {
    value: '安徽省',
    label: '安徽省',
    children: [
    { value: '合肥', label: '合肥市' },
    { value: '芜湖', label: '芜湖市' },
    { value: '蚌埠', label: '蚌埠市' },
    { value: '淮南', label: '淮南市' },
    { value: '马鞍山', label: '马鞍山市' },
    { value: '淮北', label: '淮北市' },
    { value: '铜陵', label: '铜陵市' },
    { value: '安庆', label: '安庆市' },
    { value: '黄山', label: '黄山市' },
    { value: '滁州', label: '滁州市' },
    { value: '阜阳', label: '阜阳市' },
    { value: '宿州', label: '宿州市' },
    { value: '六安', label: '六安市' },
    { value: '亳州', label: '亳州市' },
    { value: '池州', label: '池州市' },
    { value: '宣城', label: '宣城市' }
    ]
  },
  {
    value: '福建省',
    label: '福建省',
    children: [
    { value: '福州', label: '福州市' },
    { value: '厦门', label: '厦门市' },
    { value: '莆田', label: '莆田市' },
    { value: '三明', label: '三明市' },
    { value: '泉州', label: '泉州市' },
    { value: '漳州', label: '漳州市' },
    { value: '南平', label: '南平市' },
    { value: '龙岩', label: '龙岩市' },
    { value: '宁德', label: '宁德市' }
    ]
  },
  {
    value: '江西省',
    label: '江西省',
    children: [
    { value: '南昌', label: '南昌市' },
    { value: '景德镇', label: '景德镇市' },
    { value: '萍乡', label: '萍乡市' },
    { value: '九江', label: '九江市' },
    { value: '新余', label: '新余市' },
    { value: '鹰潭', label: '鹰潭市' },
    { value: '赣州', label: '赣州市' },
    { value: '吉安', label: '吉安市' },
    { value: '宜春', label: '宜春市' },
    { value: '抚州', label: '抚州市' },
    { value: '上饶', label: '上饶市' }
    ]
  },
  {
    value: '山东省',
    label: '山东省',
    children: [
    { value: '济南', label: '济南市' },
    { value: '青岛', label: '青岛市' },
    { value: '淄博', label: '淄博市' },
    { value: '枣庄', label: '枣庄市' },
    { value: '东营', label: '东营市' },
    { value: '烟台', label: '烟台市' },
    { value: '潍坊', label: '潍坊市' },
    { value: '济宁', label: '济宁市' },
    { value: '泰安', label: '泰安市' },
    { value: '威海', label: '威海市' },
    { value: '日照', label: '日照市' },
    { value: '临沂', label: '临沂市' },
    { value: '德州', label: '德州市' },
    { value: '聊城', label: '聊城市' },
    { value: '滨州', label: '滨州市' },
    { value: '菏泽', label: '菏泽市' }
    ]
  },
  {
    value: '河南省',
    label: '河南省',
    children: [
    { value: '郑州', label: '郑州市' },
    { value: '开封', label: '开封市' },
    { value: '洛阳', label: '洛阳市' },
    { value: '平顶山', label: '平顶山市' },
    { value: '安阳', label: '安阳市' },
    { value: '鹤壁', label: '鹤壁市' },
    { value: '新乡', label: '新乡市' },
    { value: '焦作', label: '焦作市' },
    { value: '濮阳', label: '濮阳市' },
    { value: '许昌', label: '许昌市' },
    { value: '漯河', label: '漯河市' },
    { value: '三门峡', label: '三门峡市' },
    { value: '南阳', label: '南阳市' },
    { value: '商丘', label: '商丘市' },
    { value: '信阳', label: '信阳市' },
    { value: '周口', label: '周口市' },
    { value: '驻马店', label: '驻马店市' }
    ]
  },
  {
    value: '湖北省',
    label: '湖北省',
    children: [
    { value: '武汉', label: '武汉市' },
    { value: '黄石', label: '黄石市' },
    { value: '十堰', label: '十堰市' },
    { value: '宜昌', label: '宜昌市' },
    { value: '襄阳', label: '襄阳市' },
    { value: '鄂州', label: '鄂州市' },
    { value: '荆门', label: '荆门市' },
    { value: '孝感', label: '孝感市' },
    { value: '荆州', label: '荆州市' },
    { value: '黄冈', label: '黄冈市' },
    { value: '咸宁', label: '咸宁市' },
    { value: '随州', label: '随州市' },
    { value: '恩施土家族苗族自治州', label: '恩施土家族苗族自治州' }
    ]
  },
  {
    value: '湖南省',
    label: '湖南省',
    children: [
    { value: '长沙', label: '长沙市' },
    { value: '株洲', label: '株洲市' },
    { value: '湘潭', label: '湘潭市' },
    { value: '衡阳', label: '衡阳市' },
    { value: '邵阳', label: '邵阳市' },
    { value: '岳阳', label: '岳阳市' },
    { value: '常德', label: '常德市' },
    { value: '张家界', label: '张家界市' },
    { value: '益阳', label: '益阳市' },
    { value: '郴州', label: '郴州市' },
    { value: '永州', label: '永州市' },
    { value: '怀化', label: '怀化市' },
    { value: '娄底', label: '娄底市' },
    { value: '湘西土家族苗族自治州', label: '湘西土家族苗族自治州' }
    ]
  },
  {
    value: '广东省',
    label: '广东省',
    children: [
    { value: '广州', label: '广州市' },
    { value: '韶关', label: '韶关市' },
    { value: '深圳', label: '深圳市' },
    { value: '珠海', label: '珠海市' },
    { value: '汕头', label: '汕头市' },
    { value: '佛山', label: '佛山市' },
    { value: '江门', label: '江门市' },
    { value: '湛江', label: '湛江市' },
    { value: '茂名', label: '茂名市' },
    { value: '肇庆', label: '肇庆市' },
    { value: '惠州', label: '惠州市' },
    { value: '梅州', label: '梅州市' },
    { value: '汕尾', label: '汕尾市' },
    { value: '河源', label: '河源市' },
    { value: '阳江', label: '阳江市' },
    { value: '清远', label: '清远市' },
    { value: '东莞', label: '东莞市' },
    { value: '中山', label: '中山市' },
    { value: '潮州', label: '潮州市' },
    { value: '揭阳', label: '揭阳市' },
    { value: '云浮', label: '云浮市' }
    ]
  },
  {
    value: '广西壮族自治区',
    label: '广西壮族自治区',
    children: [
    { value: '南宁', label: '南宁市' },
    { value: '柳州', label: '柳州市' },
    { value: '桂林', label: '桂林市' },
    { value: '梧州', label: '梧州市' },
    { value: '北海', label: '北海市' },
    { value: '防城港', label: '防城港市' },
    { value: '钦州', label: '钦州市' },
    { value: '贵港', label: '贵港市' },
    { value: '玉林', label: '玉林市' },
    { value: '百色', label: '百色市' },
    { value: '贺州', label: '贺州市' },
    { value: '河池', label: '河池市' },
    { value: '来宾', label: '来宾市' },
    { value: '崇左', label: '崇左市' }
    ]
  },
  {
    value: '海南省',
    label: '海南省',
    children: [
    { value: '海口', label: '海口市' },
    { value: '三亚', label: '三亚市' },
    { value: '三沙', label: '三沙市' },
    { value: '儋州', label: '儋州市' }
    ]
  },
  { value: '重庆', label: '重庆市' },
  {
    value: '四川省',
    label: '四川省',
    children: [
    { value: '成都', label: '成都市' },
    { value: '自贡', label: '自贡市' },
    { value: '攀枝花', label: '攀枝花市' },
    { value: '泸州', label: '泸州市' },
    { value: '德阳', label: '德阳市' },
    { value: '绵阳', label: '绵阳市' },
    { value: '广元', label: '广元市' },
    { value: '遂宁', label: '遂宁市' },
    { value: '内江', label: '内江市' },
    { value: '乐山', label: '乐山市' },
    { value: '南充', label: '南充市' },
    { value: '眉山', label: '眉山市' },
    { value: '宜宾', label: '宜宾市' },
    { value: '广安', label: '广安市' },
    { value: '达州', label: '达州市' },
    { value: '雅安', label: '雅安市' },
    { value: '巴中', label: '巴中市' },
    { value: '资阳', label: '资阳市' },
    { value: '阿坝藏族羌族自治州', label: '阿坝藏族羌族自治州' },
    { value: '甘孜藏族自治州', label: '甘孜藏族自治州' },
    { value: '凉山彝族自治州', label: '凉山彝族自治州' }
    ]
  },
  {
    value: '贵州省',
    label: '贵州省',
    children: [
    { value: '贵阳', label: '贵阳市' },
    { value: '六盘水', label: '六盘水市' },
    { value: '遵义', label: '遵义市' },
    { value: '安顺', label: '安顺市' },
    { value: '毕节', label: '毕节市' },
    { value: '铜仁', label: '铜仁市' },
    { value: '黔西南布依族苗族自治州', label: '黔西南布依族苗族自治州' },
    { value: '黔东南苗族侗族自治州', label: '黔东南苗族侗族自治州' },
    { value: '黔南布依族苗族自治州', label: '黔南布依族苗族自治州' }
    ]
  },
  {
    value: '云南省',
    label: '云南省',
    children: [
    { value: '昆明', label: '昆明市' },
    { value: '曲靖', label: '曲靖市' },
    { value: '玉溪', label: '玉溪市' },
    { value: '保山', label: '保山市' },
    { value: '昭通', label: '昭通市' },
    { value: '丽江', label: '丽江市' },
    { value: '普洱', label: '普洱市' },
    { value: '临沧', label: '临沧市' },
    { value: '楚雄彝族自治州', label: '楚雄彝族自治州' },
    { value: '红河哈尼族彝族自治州', label: '红河哈尼族彝族自治州' },
    { value: '文山壮族苗族自治州', label: '文山壮族苗族自治州' },
    { value: '西双版纳傣族自治州', label: '西双版纳傣族自治州' },
    { value: '大理白族自治州', label: '大理白族自治州' },
    { value: '德宏傣族景颇族自治州', label: '德宏傣族景颇族自治州' },
    { value: '怒江傈僳族自治州', label: '怒江傈僳族自治州' },
    { value: '迪庆藏族自治州', label: '迪庆藏族自治州' }
    ]
  },
  {
    value: '西藏自治区',
    label: '西藏自治区',
    children: [
    { value: '拉萨', label: '拉萨市' },
    { value: '日喀则', label: '日喀则市' },
    { value: '昌都', label: '昌都市' },
    { value: '林芝', label: '林芝市' },
    { value: '山南', label: '山南市' },
    { value: '那曲', label: '那曲市' },
    { value: '阿里地区', label: '阿里地区' }
    ]
  },
  {
    value: '陕西省',
    label: '陕西省',
    children: [
    { value: '西安', label: '西安市' },
    { value: '铜川', label: '铜川市' },
    { value: '宝鸡', label: '宝鸡市' },
    { value: '咸阳', label: '咸阳市' },
    { value: '渭南', label: '渭南市' },
    { value: '延安', label: '延安市' },
    { value: '汉中', label: '汉中市' },
    { value: '榆林', label: '榆林市' },
    { value: '安康', label: '安康市' },
    { value: '商洛', label: '商洛市' }
    ]
  },
  {
    value: '甘肃省',
    label: '甘肃省',
    children: [
    { value: '兰州', label: '兰州市' },
    { value: '嘉峪关', label: '嘉峪关市' },
    { value: '金昌', label: '金昌市' },
    { value: '白银', label: '白银市' },
    { value: '天水', label: '天水市' },
    { value: '武威', label: '武威市' },
    { value: '张掖', label: '张掖市' },
    { value: '平凉', label: '平凉市' },
    { value: '酒泉', label: '酒泉市' },
    { value: '庆阳', label: '庆阳市' },
    { value: '定西', label: '定西市' },
    { value: '陇南', label: '陇南市' },
    { value: '临夏回族自治州', label: '临夏回族自治州' },
    { value: '甘南藏族自治州', label: '甘南藏族自治州' }
    ]
  },
  {
    value: '青海省',
    label: '青海省',
    children: [
    { value: '西宁', label: '西宁市' },
    { value: '海东', label: '海东市' },
    { value: '海北藏族自治州', label: '海北藏族自治州' },
    { value: '黄南藏族自治州', label: '黄南藏族自治州' },
    { value: '海南藏族自治州', label: '海南藏族自治州' },
    { value: '果洛藏族自治州', label: '果洛藏族自治州' },
    { value: '玉树藏族自治州', label: '玉树藏族自治州' },
    { value: '海西蒙古族藏族自治州', label: '海西蒙古族藏族自治州' }
    ]
  },
  {
    value: '宁夏回族自治区',
    label: '宁夏回族自治区',
    children: [
    { value: '银川', label: '银川市' },
    { value: '石嘴山', label: '石嘴山市' },
    { value: '吴忠', label: '吴忠市' },
    { value: '固原', label: '固原市' },
    { value: '中卫', label: '中卫市' }
    ]
  },
  {
    value: '新疆维吾尔自治区',
    label: '新疆维吾尔自治区',
    children: [
    { value: '乌鲁木齐', label: '乌鲁木齐市' },
    { value: '克拉玛依', label: '克拉玛依市' },
    { value: '吐鲁番', label: '吐鲁番市' },
    { value: '哈密', label: '哈密市' },
    { value: '昌吉回族自治州', label: '昌吉回族自治州' },
    { value: '博尔塔拉蒙古自治州', label: '博尔塔拉蒙古自治州' },
    { value: '巴音郭楞蒙古自治州', label: '巴音郭楞蒙古自治州' },
    { value: '阿克苏地区', label: '阿克苏地区' },
    { value: '克孜勒苏柯尔克孜自治州', label: '克孜勒苏柯尔克孜自治州' },
    { value: '喀什地区', label: '喀什地区' },
    { value: '和田地区', label: '和田地区' },
    { value: '伊犁哈萨克自治州', label: '伊犁哈萨克自治州' },
    { value: '塔城地区', label: '塔城地区' },
    { value: '阿勒泰地区', label: '阿勒泰地区' }
    ]
  },
  { value: '香港', label: '香港特别行政区' },
  { value: '澳门', label: '澳门特别行政区' },
  {
    value: '台湾省',
    label: '台湾省',
    children: [
    { value: '台北', label: '台北市' },
    { value: '新北', label: '新北市' },
    { value: '桃园', label: '桃园市' },
    { value: '新竹', label: '新竹市' },
    { value: '台中', label: '台中市' },
    { value: '台南', label: '台南市' },
    { value: '高雄', label: '高雄市' }
    ]
  }
]
