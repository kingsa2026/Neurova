import type { App } from 'vue'
import Alert from 'ant-design-vue/es/alert'
import AutoComplete from 'ant-design-vue/es/auto-complete'
import Badge from 'ant-design-vue/es/badge'
import Breadcrumb, { BreadcrumbItem } from 'ant-design-vue/es/breadcrumb'
import Button from 'ant-design-vue/es/button'
import Checkbox, { CheckboxGroup } from 'ant-design-vue/es/checkbox'
import Col from 'ant-design-vue/es/col'
import ConfigProvider from 'ant-design-vue/es/config-provider'
import DatePicker, { RangePicker } from 'ant-design-vue/es/date-picker'
import Descriptions, { DescriptionsItem } from 'ant-design-vue/es/descriptions'
import Divider from 'ant-design-vue/es/divider'
import Drawer from 'ant-design-vue/es/drawer'
import Dropdown from 'ant-design-vue/es/dropdown'
import Empty from 'ant-design-vue/es/empty'
import Form, { FormItem } from 'ant-design-vue/es/form'
import Input, { InputPassword, InputSearch, Textarea } from 'ant-design-vue/es/input'
import InputNumber from 'ant-design-vue/es/input-number'
import List, { ListItem, ListItemMeta } from 'ant-design-vue/es/list'
import Menu, { MenuDivider, MenuItem } from 'ant-design-vue/es/menu'
import message from 'ant-design-vue/es/message'
import Modal from 'ant-design-vue/es/modal'
import Pagination from 'ant-design-vue/es/pagination'
import Popconfirm from 'ant-design-vue/es/popconfirm'
import Popover from 'ant-design-vue/es/popover'
import Progress from 'ant-design-vue/es/progress'
import Radio, { RadioButton, RadioGroup } from 'ant-design-vue/es/radio'
import Rate from 'ant-design-vue/es/rate'
import Result from 'ant-design-vue/es/result'
import Row from 'ant-design-vue/es/row'
import Segmented from 'ant-design-vue/es/segmented'
import Select, { SelectOptGroup, SelectOption } from 'ant-design-vue/es/select'
import Slider from 'ant-design-vue/es/slider'
import Space from 'ant-design-vue/es/space'
import Spin from 'ant-design-vue/es/spin'
import Steps, { Step } from 'ant-design-vue/es/steps'
import Switch from 'ant-design-vue/es/switch'
import Table, { TableColumn } from 'ant-design-vue/es/table'
import Tabs, { TabPane } from 'ant-design-vue/es/tabs'
import Tag from 'ant-design-vue/es/tag'
import TimePicker from 'ant-design-vue/es/time-picker'
import Timeline, { TimelineItem } from 'ant-design-vue/es/timeline'
import Tooltip from 'ant-design-vue/es/tooltip'
import Tree from 'ant-design-vue/es/tree'
import TreeSelect from 'ant-design-vue/es/tree-select'
import Upload, { UploadDragger } from 'ant-design-vue/es/upload'
import cssinjs from 'ant-design-vue/es/_util/cssinjs'
import theme from 'ant-design-vue/es/theme'

export type { ConfigProviderProps } from 'ant-design-vue/es/config-provider'
export type { UploadFile } from 'ant-design-vue/es/upload'
export {
  Alert, AutoComplete, Badge, Breadcrumb, BreadcrumbItem, Button, Checkbox, CheckboxGroup,
  Col, ConfigProvider, DatePicker, RangePicker, Descriptions, DescriptionsItem, Divider,
  Drawer, Dropdown, Empty, Form, FormItem, Input, InputNumber, InputPassword, InputSearch,
  Textarea, List, ListItem, ListItemMeta, Menu, MenuDivider, MenuItem, Pagination, Popconfirm,
  Popover, Progress, Radio, RadioButton, RadioGroup, Rate, Result, Row, Segmented, Select,
  SelectOptGroup, SelectOption, Slider, Space, Spin, Step, Steps, Switch, Table, TableColumn,
  Tabs, TabPane, Tag, TimePicker, Timeline, TimelineItem, Tooltip, Tree, TreeSelect, Upload,
  UploadDragger, cssinjs, message, Modal, theme,
}

const components = [
  Alert, AutoComplete, Badge, Breadcrumb, BreadcrumbItem, Button, Checkbox, CheckboxGroup,
  Col, ConfigProvider, DatePicker, RangePicker, Descriptions, DescriptionsItem, Divider,
  Drawer, Dropdown, Empty, Form, FormItem, Input, InputNumber, InputPassword, InputSearch,
  Textarea, List, ListItem, ListItemMeta, Menu, MenuDivider, MenuItem, Modal, Pagination, Popconfirm,
  Popover, Progress, Radio, RadioButton, RadioGroup, Rate, Result, Row, Segmented, Select,
  SelectOptGroup, SelectOption, Slider, Space, Spin, Step, Steps, Switch, Table, TableColumn,
  Tabs, TabPane, Tag, TimePicker, Timeline, TimelineItem, Tooltip, Tree, TreeSelect, Upload,
  UploadDragger,
]

const install = (app: App) => {
  for (const component of components) {
    if ('install' in component && typeof component.install === 'function') {
      app.use(component)
    }
  }
  app.use(cssinjs.StyleProvider)
  app.config.globalProperties.$message = message
  app.config.globalProperties.$info = Modal.info
  app.config.globalProperties.$success = Modal.success
  app.config.globalProperties.$error = Modal.error
  app.config.globalProperties.$warning = Modal.warning
  app.config.globalProperties.$confirm = Modal.confirm
  app.config.globalProperties.$destroyAll = Modal.destroyAll
  return app
}

export default { install }
