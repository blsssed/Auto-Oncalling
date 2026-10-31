// shadcn-vue 基础组件聚合出口。主题令牌在 src/styles.css 中映射到
// 随明暗主题切换的 CSS 变量，因此这些组件自动适配浅色/深色。
export { Badge, badgeVariants } from "./badge"
export type { BadgeVariants } from "./badge"
export { Button, buttonVariants } from "./button"
export type { ButtonVariants } from "./button"
export {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from "./card"
export { Input } from "./input"
export { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "./select"
export { Separator } from "./separator"
export { Skeleton } from "./skeleton"
export {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableEmpty,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow
} from "./table"
export { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs"
export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip"
