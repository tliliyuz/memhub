import React from 'react'
import { useNavigate } from '@tanstack/react-router'
import { ArrowRight, Moon, Sun } from 'lucide-react'
import { useSearch } from '@/context/search-provider'
import { useTheme } from '@/context/theme-provider'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { sidebarData } from './layout/data/sidebar-data'

/** Ctrl/⌘+K：跳转页面 + 切换主题。知识检索走节点页的搜索框。 */
export function CommandMenu() {
  const navigate = useNavigate()
  const { setTheme } = useTheme()
  const { open, setOpen } = useSearch()

  const runCommand = React.useCallback(
    (command: () => unknown) => {
      setOpen(false)
      command()
    },
    [setOpen],
  )

  return (
    <CommandDialog modal open={open} onOpenChange={setOpen}>
      <CommandInput placeholder='跳转到…' />
      <CommandList>
        <CommandEmpty>没有匹配项</CommandEmpty>
        {sidebarData.navGroups.map((group) => (
          <CommandGroup key={group.title} heading={group.title}>
            {group.items.map((navItem, index) => {
              if (!navItem.url) return null
              return (
                <CommandItem
                  key={`${navItem.url}-${index}`}
                  value={navItem.title}
                  onSelect={() => {
                    runCommand(() => navigate({ to: navItem.url }))
                  }}
                >
                  <div className='flex size-4 items-center justify-center'>
                    <ArrowRight className='size-2 text-muted-foreground/80' />
                  </div>
                  {navItem.title}
                </CommandItem>
              )
            })}
          </CommandGroup>
        ))}
        <CommandSeparator />
        <CommandGroup heading='主题'>
          <CommandItem onSelect={() => runCommand(() => setTheme('light'))}>
            <Sun /> 浅色
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => setTheme('dark'))}>
            <Moon /> 深色
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}
